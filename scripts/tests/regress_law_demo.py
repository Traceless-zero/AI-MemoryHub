# -*- coding: utf-8 -*-
"""
法条 demo 回归用例（常驻·不污染真仓库）
=========================================
目的：
  固化「同包多锚点 + 法条号两 keyword 分解」场景，防止 OR-fail-safe / rule#1 之类
  「自以为是层」重新把 gold 挤出 top5（2026-08-27 真实踩过的坑：窄问"民法典32条"
  本应第32条居首，却因 query_anchors 的 OR-fail-safe 破坏性 final.pop() 把 32 弹到 #3）。

  本用例是「校准基准」非一次性脚本，长期保留（别丢进 to_delete/）。

fixture：自包含。运行期在 tempfile 写一份民法典监护条款 .md（与记忆库
  `memory/其他/法律/民法典/民法典监护条款.md` 同构），建索引、跑断言、结束后删临时目录——绝不碰真实 memory/。

断言：
  1. 窄问 "民法典32条"（keywords=['民法典','32条']）→ top1 必须是「第32条」锚点
     （gold 不被挤出；这正是 OR-fail-safe bug 破坏的性质）。
  2. 同包三章（第32/33/34条）都必须出现在 top5（同包多锚点宽召回，不丢章）。
  3. 宽问 "民法典"（keywords=['民法典']）→ 三章并列命中，全部在 top5。

用法：
    cd E:/BaiduNetdiskDownload/项目/AIMH
    python scripts/tests/regress_law_demo.py
"""
import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, PROJECT)

from hma.hma_core import Memory  # noqa: E402

# 与根目录 民法典监护条款.demo.md 同构的自包含 fixture
FIXTURE_MD = """---
title: 民法典监护条款
summary: 民法典监护制度测试包（第32-34条），验证法律结构化内容在 AIMH 的落库与召回
tags: [法律, 民法典, 监护, demo]
linked: []
anchors:
  - Chapter: "第32条 公职监护兜底"
    about: "无适格监护人时，由民政部门或被监护人住所地的居民委员会、村民委员会担任监护人（公职监护兜底）"
    keywords: ["公职监护兜底", "民法典", "32条", "民政部门", "村民委员会", "居民委员会", "被监护人"]
  - Chapter: "第33条 意定监护"
    about: "具有完全民事行为能力的成年人可事先协商并以书面形式指定自己的监护人（意定监护）"
    keywords: ["意定监护", "民法典", "33条", "成年人", "近亲属", "书面指定监护人"]
  - Chapter: "第34条 监护职责与资格撤销"
    about: "监护人代理被监护人实施民事法律行为，失职或侵害权益须担责，严重可撤销监护人资格"
    keywords: ["监护职责", "撤销监护人资格", "民法典", "34条", "监护人", "被监护人", "代理民事法律行为"]
person:
  - 监护人: ["监护人", "民政部门"]
  - 被监护人: ["被监护人"]
event_date: "—"
location: []
topic:
  - 民法典: ["民法典", "监护", "监护制度"]
pkage_created: 2026-08-27
pkage_updated: 2026-08-27
---

# 民法典监护条款（测试包）

## 第32条 公职监护兜底

没有依法具有监护资格的人的，监护人由民政部门担任，也可以由具备履行监护职责条件的被监护人住所地的居民委员会、村民委员会担任。

## 第33条 意定监护

具有完全民事行为能力的成年人，可以与其近亲属、其他愿意担任监护人的个人或者组织事先协商，以书面形式确定自己的监护人，在自己丧失或者部分丧失民事行为能力时，由该监护人履行监护职责。

## 第34条 监护职责与资格撤销

监护人的职责是代理被监护人实施民事法律行为，保护被监护人的人身权利、财产权利以及其他合法权益等。监护人依法履行监护职责产生的权利，受法律保护。监护人不履行监护职责或者侵害被监护人合法权益的，应当承担法律责任；严重时会撤销监护人资格。
"""


def titles_of(top):
    return [r[1] for r in top] if top else []


def main():
    base = tempfile.mkdtemp(prefix="aimh_law_regress_")
    pkg = os.path.join(base, "law_pkg")
    os.makedirs(pkg)
    md_path = os.path.join(pkg, "民法典监护条款.demo.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(FIXTURE_MD)

    m = Memory(pkg)
    m.rebuild_all()

    fails = []

    # —— 断言 1：窄问 民法典32条 → 第32条 必须居首 ——
    q = "民法典32条"
    top = m.query_anchors(q, top_k=5, keywords=["民法典", "32条"])
    ts = titles_of(top)
    top1 = ts[0] if ts else ""
    if "第32条" not in top1:
        fails.append(f"断言1 FAIL：窄问'{q}' top1='{top1}'，期望含'第32条'（gold 被挤出）")
    else:
        print(f"[PASS] 断言1 窄问'{q}' top1='{top1}' ✅")

    # —— 断言 2：同包三章都在 top5 ——
    need = ["第32条", "第33条", "第34条"]
    missing = [n for n in need if not any(n in t for t in ts)]
    if missing:
        fails.append(f"断言2 FAIL：窄问'{q}' 缺失章 {missing}（同包多锚点漏召回） top5={ts}")
    else:
        print(f"[PASS] 断言2 窄问'{q}' 三章(32/33/34)全在 top5 ✅")

    # —— 断言 3：宽问 民法典 → 三章并列全在 ——
    q2 = "民法典"
    top2 = m.query_anchors(q2, top_k=5, keywords=["民法典"])
    ts2 = titles_of(top2)
    missing2 = [n for n in need if not any(n in t for t in ts2)]
    if missing2:
        fails.append(f"断言3 FAIL：宽问'{q2}' 缺失章 {missing2} top5={ts2}")
    else:
        print(f"[PASS] 断言3 宽问'{q2}' 三章并列全在 top5 ✅")

    print(f"\n窄问 top5: {ts}")
    print(f"宽问 top5: {ts2}")

    m.close()
    shutil.rmtree(base, ignore_errors=True)

    print("=" * 56)
    if fails:
        for f in fails:
            print(f"  {f}")
        print("总判定：存在失败 ❌")
        sys.exit(1)
    print("总判定：ALL GREEN ✅（法条 demo 回归通过，gold 未被挤出）")
    sys.exit(0)


if __name__ == "__main__":
    main()
