# -*- coding: utf-8 -*-
"""periodic_review.py —— HMA 定时整合（检索路径 → 提炼 → 写入用户数据.md + 整理.md）。

设计（用户 2026-07-27 终版）：
  - 清单 memory/整理/_清单.md 只列「检索路径」（glob 模式），不写死具体文件；
    脚本按路径找出文件（各项目 约定.md、各文章综述包…）。
  - 提炼结果统一写入 memory/用户/用户数据.md 的「定时整合」段落（确定性段落，每周刷新不堆积）。
  - daylog 近 7 天由脚本固定处理：提炼用户透露的偏好/厌恶、把琐碎话题收成连贯主题
    → 写入 用户数据.md（同一段落）+ 汇总写入 memory/整理/梳理成果-YYYY-MM-DD.md。
  - 触发：WorkBuddy automation 每周调用。

纪律：只读源、提炼后写入用户数据.md、daylog 汇总写入整理.md；不修改被读源文件。
"""
import os
import sys
import glob as _glob
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from hma.hma_core import Memory  # noqa: E402
from hma.daylog import days_in_range, read_day  # noqa: E402
from hma.llm_adapter import get_adapter  # noqa: E402

USER_ROOT = os.path.join(REPO, "memory", "用户")
USER_DATA_ID = "用户数据"
REVIEW_DIR = os.path.join(REPO, "memory", "整理")
MANIFEST = os.path.join(REVIEW_DIR, "_清单.md")
DAYLOG_ROOT = os.path.join(REPO, "memory", "日志")
WINDOW_DAYS = 7

REVIEW_START = "<!-- HMA-REVIEW:START -->"
REVIEW_END = "<!-- HMA-REVIEW:END -->"


def parse_patterns():
    pats = []
    if os.path.isfile(MANIFEST):
        for line in open(MANIFEST, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pats.append(line)
    return pats


def expand(pat):
    """把检索路径（glob 或目录）展开为具体 .md 文件列表，去重、跳过 _ 开头。"""
    base = Path(REPO)
    matched = list(base.glob(pat))
    files, seen = [], set()
    for p in matched:
        if p.is_dir():
            files += [x for x in p.glob("**/*.md")]
        elif p.is_file() and p.suffix == ".md":
            files.append(p)
    out = []
    for f in files:
        if f.name.startswith("_"):
            continue
        fs = str(f)
        if fs not in seen:
            seen.add(fs)
            out.append(fs)
    return out


def read_sources(files):
    out = []
    for fp in files:
        try:
            body = open(fp, encoding="utf-8").read()
            if body.strip():
                out.append((os.path.relpath(fp, REPO), body))
        except Exception:
            pass
    return out


def distill(label, sources, instruction):
    """多源拼合后提炼：有 HMA_LLM 则按 instruction 归纳，否则降级为原文拼合。"""
    combined = "\n\n---\n\n".join(
        "# 来源 %s\n%s" % (name, body) for name, body in sources)
    adapter = get_adapter() if os.environ.get("HMA_LLM") else None
    if adapter is not None:
        prompt = (
            "你是 HMA 记忆整理器。下面是主题「%s」相关的原始记忆材料。\n%s\n\n"
            "只基于原文，不编造；原文没有的维度就不写。用中文、简洁、可检索。\n\n"
            % (label, instruction)
        ) + combined
        try:
            resp = adapter.chat([{"role": "user", "content": prompt}],
                                tools=None, tool_choice="auto")
            return adapter.content_text(resp)
        except Exception as e:
            combined += "\n\n[LLM 提炼失败，已降级为原文拼合：%s]" % e
    return ("# %s（纯规则降级：未配 HMA_LLM，原文拼合）\n\n" % label) + combined


def collect_daylog(days=WINDOW_DAYS):
    out = []
    end = _date_today()
    start = end - __import__("datetime").timedelta(days=days - 1)
    try:
        pkgs = days_in_range(DAYLOG_ROOT, start.isoformat(), end.isoformat())
    except Exception:
        return out
    for d, _rid, _title in pkgs:
        pkg = read_day(DAYLOG_ROOT, d)
        if pkg and pkg.body.strip():
            out.append((d, pkg.body))
    return out


def _date_today():
    import datetime
    return datetime.date.today()


def upsert_block(body, block):
    """在 body 中替换/插入确定性「定时整合」段落（idempotent，不堆积）。"""
    s = body.find(REVIEW_START)
    if s != -1:
        e = body.find(REVIEW_END, s)
        if e != -1:
            body = body[:s] + body[e + len(REVIEW_END):]
    return body.rstrip() + "\n\n" + REVIEW_START + "\n" + block + "\n" + REVIEW_END + "\n"


def main():
    os.makedirs(USER_ROOT, exist_ok=True)
    os.makedirs(REVIEW_DIR, exist_ok=True)
    today = _date_today().isoformat()
    mem = Memory(USER_ROOT)
    pkg = mem.read(USER_DATA_ID)
    title = pkg.title if pkg else "用户数据"
    summary = pkg.summary if pkg else "用户长期数据（偏好/方法论/身份锚点/踩坑/事实）"
    tags = pkg.tags if pkg else ["用户"]
    body = pkg.body if pkg else ""
    mem.close()

    sections = []  # 写入用户数据.md 的整合段落

    # 1) 清单检索路径：项目约定 / 文章理解
    for pat in parse_patterns():
        files = expand(pat)
        if not files:
            print("  [跳过] 路径 %s 无可读文件" % pat)
            continue
        sources = read_sources(files)
        label = "检索路径 %s" % pat
        ins = ("请提炼成可长期沉淀的「用户数据」条目：聚焦其中稳定的约定、纪律、"
               "方法论、用户对文章/资料的理解与结论。去冗余、可检索。")
        text = distill(label, sources, ins)
        sections.append("### 来自 %s\n\n%s" % (pat, text))
        print("  已提炼路径: %s (源 %d)" % (pat, len(sources)))

    # 2) daylog 近 7 天：偏好/厌恶 + 连贯话题
    daylog = collect_daylog(WINDOW_DAYS)
    if daylog:
        dsrc = [("daylog:%s" % d, b) for d, b in daylog]
        pref_ins = ("请从近期 daylog 中提炼用户透露出的稳定偏好、厌恶、价值观信号，"
                    "以及反复出现的主题；把琐碎的日常记录收成连贯的话题，不要逐条罗列流水账。")
        pref = distill("daylog 偏好信号", dsrc, pref_ins)
        sections.append("### 近期偏好与信号（来自 daylog）\n\n" + pref)
        # daylog 汇总 → 整理.md
        sum_ins = ("请把这 7 天 daylog 汇总成一份连贯的周报：关键主题、用户偏好/厌恶信号、"
                   "待办/开放问题。去琐碎、成连贯叙述。")
        summary_text = distill("daylog 周汇总", dsrc, sum_ins)
        out_path = os.path.join(REVIEW_DIR, "梳理成果-%s.md" % today)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(("# HMA 定时梳理成果 %s\n\n（daylog 周汇总备份；偏好信号已并入 "
                     "memory/用户/用户数据.md）\n\n" % today) + summary_text.rstrip() + "\n")
        print("  已汇总 daylog (%d 天) → %s" % (len(daylog), out_path))
    else:
        print("  [跳过] 近 %d 天无 daylog" % WINDOW_DAYS)

    if not sections:
        print("本次无内容可整合")
        return

    block = "## 定时整合（%s）\n\n" % today + "\n\n".join(sections)
    new_body = upsert_block(body, block)
    mem2 = Memory(USER_ROOT)
    mem2.write(id=USER_DATA_ID, title=title, summary=summary, tags=tags, body=new_body)
    mem2.close()
    print("已写入用户数据.md（定时整合段落，%d 个子区块）" % len(sections))


if __name__ == "__main__":
    main()
