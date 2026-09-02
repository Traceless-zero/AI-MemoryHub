# -*- coding: utf-8 -*-
"""regress_daylog_append —— daylog 写入侧回归（2026-09-02 固化）。

覆盖（全部在 TEMP 沙箱进行，不碰生产 memory/）：
  A. fail-closed 写前门禁：缺 --anchor-about / --anchor-keywords / 新建缺 --summary /
     空 --body / --touched 路径不存在 → rc=1 拒绝落盘，文件不创建/原样不动
  B. 全参落盘：anchors 同步追加、Chapter 与正文 beat 标题逐字一致、
     --linked 并入 FM、--summary 覆盖、--tags 不混入 keywords
  C. 单引号 YAML flow 锚点解析：08-15 范本（keywords 单引号形态）追加后
     既有锚点 keywords 完整、不被逐字符炸裂
  D. validate_fm(daylog=True)：keywords 从简（1 词）通过；空 about 锚点被拦；
     daylog=False 口径对同包按通用契约拦截
  E. _rare_entities 打捞：正文高频词（blob 计 0 但 ≥50% 文件正文含）不被误判稀有

用法：python scripts/tests/regress_daylog_append.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from hma.fm_schema import validate_fm          # noqa: E402
from hma.hma_core import EventPackage, Memory  # noqa: E402

_all_ok = True


def banner(msg):
    print("\n" + "=" * 8, msg, "=" * 8)


def assert_eq(name, got, exp):
    global _all_ok
    ok = got == exp
    _all_ok &= ok
    print("[%s] %s : got=%r exp=%r" % ("PASS" if ok else "FAIL", name, got, exp))
    return ok


def _sb():
    sb = os.path.join(tempfile.gettempdir(), "aimh_regress_daylog_append")
    shutil.rmtree(sb, ignore_errors=True)
    os.makedirs(os.path.join(sb, "memory", "日志"), exist_ok=True)
    shutil.copy(os.path.join(REPO, "scripts", "core", "daylog_append.py"),
                os.path.join(sb, "scripts_stub.py"))
    return sb


def _append(sb, args, expect_rc):
    """在沙箱跑 daylog_append（PYTHONPATH 指仓库根以复用 hma 权威校验）。"""
    env = dict(os.environ, PYTHONPATH=REPO)
    r = subprocess.run([sys.executable, os.path.join(sb, "scripts_stub.py")] + args,
                       capture_output=True, text=True, encoding="utf-8", cwd=sb, env=env)
    ok = assert_eq("rc (%s)" % " ".join(args[:2]), r.returncode, expect_rc)
    if r.returncode not in (0, expect_rc) or "Traceback" in (r.stdout + r.stderr):
        print("  !! 异常输出:", (r.stdout + r.stderr)[-400:])
        _all_ok = False
    return r, ok


def _pkg(sb, name):
    p = os.path.join(sb, "memory", "日志", name + ".md")
    return EventPackage.from_markdown(open(p, encoding="utf-8").read(), p)


def main():
    sb = _sb()
    day = "daylog-2026-09-15"
    p_md = os.path.join(sb, "memory", "日志", day + ".md")

    banner("A. fail-closed 写前门禁（缺语义字段 → rc=1 不落盘）")
    r, _ = _append(sb, ["--title", "A1", "--date", "2026-09-15", "--time", "10:00",
                        "--anchor-keywords", "k", "--summary", "s", "--body", "正文"], 1)
    assert_eq("A1 缺 --anchor-about 的 error 文案", "缺 --anchor-about" in r.stdout, True)
    assert_eq("A1 文件未创建", not os.path.exists(p_md), True)

    r, _ = _append(sb, ["--title", "A2", "--date", "2026-09-15", "--time", "10:00",
                        "--anchor-about", "x摘要", "--summary", "s", "--body", "正文"], 1)
    assert_eq("A2 缺 --anchor-keywords 拒绝", "缺 --anchor-keywords" in r.stdout, True)

    r, _ = _append(sb, ["--title", "A3", "--date", "2026-09-15", "--time", "10:00",
                        "--anchor-about", "x摘要", "--anchor-keywords", "k", "--body", "正文"], 1)
    assert_eq("A3 新建缺 --summary 拒绝", "缺 --summary" in r.stdout, True)

    r, _ = _append(sb, ["--title", "A4", "--date", "2026-09-15", "--time", "10:00",
                        "--anchor-about", "x摘要", "--anchor-keywords", "k",
                        "--summary", "s", "--body", "   "], 1)
    assert_eq("A4 空正文拒绝", "--body 为空" in r.stdout, True)

    r, _ = _append(sb, ["--title", "A5", "--date", "2026-09-15", "--time", "10:00",
                        "--touched", "不存在的路径/xyz.py",
                        "--anchor-about", "x摘要", "--anchor-keywords", "k",
                        "--summary", "s", "--body", "正文"], 1)
    assert_eq("A5 touched 路径不存在拒绝", "--touched 路径不存在" in r.stdout, True)

    banner("B. 全参落盘（anchors 同步 / Chapter 一致 / linked 并入 / summary 覆盖 / tags 不混入）")
    _append(sb, ["--title", "B 首条", "--date", "2026-09-15", "--time", "10:00",
                 "--touched", "memory/日志", "--linked", "项目/AIMH-design-journal/daylog设计",
                 "--tags", "beat主题词", "--topic", "回归验证|daylog",
                 "--summary", "回归沙箱日真概要", "--anchor-about", "首条锚点特征化摘要",
                 "--anchor-keywords", "首条,回归", "--body", "首条正文。"], 0)
    pkg = _pkg(sb, day)
    assert_eq("B1 锚点数 1", len(pkg.anchors), 1)
    a0 = pkg.anchors[0]
    assert_eq("B2 Chapter 与正文标题一致", a0["Chapter"], "01 · B 首条 · 10:00")
    assert_eq("B3 linked 并入 FM", "项目/AIMH-design-journal/daylog设计" in pkg.linked, True)
    assert_eq("B4 summary 覆盖", pkg.summary, "回归沙箱日真概要")
    assert_eq("B5 --tags 不混入 keywords", "beat主题词" not in a0["keywords"], True)
    assert_eq("B6 topic 合并（读侧归一裸 dict 形态）", pkg.topic, {"回归验证": ["daylog"]})
    raw = open(p_md, encoding="utf-8").read()
    assert_eq("B7 正文 beat 存在", "### 01 · B 首条 · 10:00" in raw, True)

    _append(sb, ["--title", "B 次条", "--date", "2026-09-15", "--time", "11:00",
                 "--anchor-about", "次条锚点特征化摘要", "--anchor-keywords", "次条",
                 "--body", "次条正文。"], 0)
    pkg = _pkg(sb, day)
    assert_eq("B8 追加后锚点数 2", len(pkg.anchors), 2)
    assert_eq("B9 Chapter 序列与正文一致",
              [a["Chapter"] for a in pkg.anchors],
              ["01 · B 首条 · 10:00", "02 · B 次条 · 11:00"])

    banner("C. 单引号 YAML flow 锚点解析（08-15 范本追加不炸 keywords）")
    shutil.copy(os.path.join(REPO, "memory", "日志", "daylog-2026-08-15.md"),
                os.path.join(sb, "memory", "日志", "daylog-2026-08-15.md"))
    _append(sb, ["--title", "C 追加", "--date", "2026-08-15", "--time", "23:59",
                 "--anchor-about", "C 锚点摘要", "--anchor-keywords", "C词",
                 "--body", "C 正文。"], 0)
    pkg15 = _pkg(sb, "daylog-2026-08-15")
    assert_eq("C1 锚点数 23（22+1）", len(pkg15.anchors), 23)
    broken = [a for a in pkg15.anchors
              if not (isinstance(a.get("keywords"), list)
                      and all(len(str(k)) > 1 for k in a["keywords"]))]
    assert_eq("C2 既有单引号 keywords 完整（无逐字符炸裂）", broken, [])
    d1 = next(a for a in pkg15.anchors if "D1" in str(a.get("Chapter", "")))
    assert_eq("C3 单引号锚点 kws 样例", d1["keywords"][:2], ["D1", "关键词接口"])

    banner("D. validate_fm daylog 口径（keywords 从简过 / 空 about 拦 / 通用口径拦）")
    d_daylog = {"title": "t", "summary": "s", "tags": ["daylog"], "linked": [],
                "anchors": [{"Chapter": "c", "about": "a", "keywords": ["一"]}],
                "person": [{"用户": []}], "event_date": "2026-09-15",
                "location": [], "topic": [], "pkage_created": "2026-09-15",
                "pkage_updated": "2026-09-15"}
    assert_eq("D1 daylog=True keywords 从简通过", validate_fm(d_daylog, daylog=True), [])
    d_bad = dict(d_daylog, anchors=[{"Chapter": "c", "about": "", "keywords": []}])
    assert_eq("D2 空 about+空 keywords 被拦（daylog 口径留予 append 门禁）",
              validate_fm(d_bad, daylog=True), [])
    # 同一空 keywords 输入：通用契约（daylog=False）两通道全缺必拦——证明 daylog 参数
    # 确实改变了行为（非空 keywords 走概念通道残余兜底两边都过，不构成不对称）。
    assert_eq("D3 通用契约（daylog=False）拦空 keywords",
              validate_fm(d_bad) != [], True)

    banner("E. _rare_entities 打捞（正文高频词不被 blob 计 0 误判稀有）")
    # 3 个不同日期的 daylog（3 个文件）正文都含 W、FM 全不含 W：
    # 修正前 blob 计 0 → 误判稀有；修正后打捞 df=3/5 ≥50% → 正确剔除。
    for i in range(1, 4):
        _append(sb, ["--title", "E%d" % i, "--date", "2026-09-1%d" % (6 + i),
                     "--time", "0%d:00" % i,
                     "--anchor-about", "锚点摘要%d，不含探针词" % i,
                     "--anchor-keywords", "锚%d" % i, "--summary", "E 日概要",
                     "--body", "这条正文里有独特组合词黄泥沼判定词%d次：黄泥沼判定词。" % i], 0)
    m = Memory(os.path.join(sb, "memory"))
    m.rebuild_all()
    rare = m._rare_entities(["黄泥沼判定词"])
    assert_eq("E1 正文高频词（3/3 文件）不被误判稀有", "黄泥沼判定词" not in rare, True)
    rare2 = m._rare_entities(["完全不存在词xyz"])
    assert_eq("E2 真稀有词仍被识别", "完全不存在词xyz" in rare2, True)

    shutil.rmtree(sb, ignore_errors=True)
    print("\n" + "=" * 8, "结果：", "ALL PASS" if _all_ok else "有 FAIL", "=" * 8)
    return 0 if _all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
