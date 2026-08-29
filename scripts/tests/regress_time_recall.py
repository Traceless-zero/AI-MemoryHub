# -*- coding: utf-8 -*-
"""类型 6 硬时间过滤（time_filter）· 召回测试（recall）。

金标准（gold）来自权威源 .md front-matter 的 event_date，用**透明、独立**的
字符串判定（startswith / 正则匹配月份），不调用 parse_time_hint、不调用
time_filter——避免实现自身校验自身。问题走 Memory.filter_by_time（真实后端，
memory_time_filter MCP 工具将直接包它）路径，模拟「3月开了哪些会」类自然语言问。

两者对账：工具返回的包集合 == 从 .md 抽出的金标准集合，才算召回通过。

用法（仓库根下）：
  python scripts/tests/regress_time_recall.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from hma.hma_core import EventPackage, Memory

MEM = os.path.join(REPO, "memory")


def collect():
    """(dir_rel, pkg) 列表；pkg 用索引构建同款解析器从 .md 抽出（gold 源）。"""
    items = []
    for r, _, fs in os.walk(MEM):
        for f in fs:
            if not f.endswith(".md"):
                continue
            p = os.path.join(r, f)
            try:
                pkg = EventPackage.from_markdown_fm_only(
                    open(p, encoding="utf-8").read(), filepath=p)
            except Exception:
                continue
            dir_rel = os.path.relpath(r, MEM).replace("\\", "/")
            items.append((dir_rel, pkg))
    return items


def gold(hint, scope, gold_pred):
    """gold = dir 集合，满足 gold_pred(event_date) 且（若有 scope）dir 含 scope。"""
    items = collect()
    out = set()
    for dir_rel, pkg in items:
        if scope and scope not in dir_rel:
            continue
        ed = pkg.event_date or ""
        if gold_pred(ed):
            out.add(dir_rel)
    return out


def tool(hint, scope=None):
    m = Memory("memory")
    try:
        res = m.filter_by_time(hint, scope=scope)
    finally:
        m.close()
    # 归一：package_id 字符串化、去反斜杠
    return set(str(x).replace("\\", "/") for x in res)


# 透明 gold 判定（独立，不碰 parse_time_hint / time_filter）
QUESTIONS = [
    {"q": "2026 年 3 月（按事件时间）收录了哪些记忆？", "hint": "2026年3月",
     "gold_pred": lambda ed: bool(ed) and ed.startswith("2026-03")},
    {"q": "三月（不限年份）收录了哪些记忆？", "hint": "三月",
     "gold_pred": lambda ed: bool(ed) and re.match(r"^\d{4}-03", ed) is not None},
    {"q": "对话记录归档目录下 2026 年的记忆有哪些？", "hint": "2026年",
     "scope": "其他/对话记录归档",
     "gold_pred": lambda ed: bool(ed) and ed.startswith("2026")},
    {"q": "雪莱相关记忆（event_date 1792-1822）在 2026 年 3 月？", "hint": "2026年3月",
     "scope": "人物/雪莱（诗人）",
     "gold_pred": lambda ed: bool(ed) and ed.startswith("2026-03")},
]

fails = []
print("=" * 70)
print("类型 6 硬时间过滤 · 召回测试（gold=从 .md event_date 透明判定；答=filter_by_time）")
print("=" * 70)
for item in QUESTIONS:
    g = gold(item["hint"], item.get("scope"), item["gold_pred"])
    ans = tool(item["hint"], item.get("scope"))
    passed = (ans == g)
    print(f"\n● {item['q']}")
    print(f"    gold(.md) = {sorted(g)}")
    print(f"    工具答   = {sorted(ans)}")
    print(f"    {'PASS' if passed else 'FAIL'}")
    if not passed:
        print(f"    差集 gold-tool = {sorted(g - ans)} | tool-gold = {sorted(ans - g)}")
    if not passed:
        fails.append(item["q"])

print("\n" + "=" * 70)
print("召回结果:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
print("=" * 70)
sys.exit(1 if fails else 0)
