# -*- coding: utf-8 -*-
"""类型 8 计数 · 召回测试（recall，非单测）。

金标准（gold）来自权威源 .md front-matter，用项目自己的索引构建解析器
EventPackage.from_markdown_fm_only 抽取（与引擎/索引完全独立的「写」管线对照
「读」管线；不碰 db_aggregate、不碰 index.db）。问题走真实 MCP 工具
memory_aggregate（server.dispatch）路径，模拟调用方 AI 实际提问。两者对账：
工具答数 == 从 .md 抽出的金标准，才算召回通过。gold 抽取到的实体/目录显式打印，
供人工审计。

用法（仓库根下）：
  python scripts/tests/regress_aggregate_recall.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from hma import server
from hma.hma_core import EventPackage

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


def gold(unit, scope=None, dateprefix=None):
    items = collect()
    if scope:
        items = [it for it in items if scope in it[0]]
    if dateprefix:
        items = [it for it in items
                 if str((it[1].event_date or "")).startswith(dateprefix)]
    if unit == "packages":
        return len(set(d for d, _ in items))
    col = {"persons": "person", "locations": "location", "topics": "topic"}[unit]
    names = set()
    for _, pkg in items:
        d = getattr(pkg, col) or {}
        if isinstance(d, dict):
            names.update(d.keys())
    return names


def tool(unit, scope=None, dateprefix=None):
    a = {"unit": unit}
    if scope:
        a["scope"] = scope
    if dateprefix:
        a["event_date_like"] = dateprefix
    req = {"method": "tools/call", "id": 1,
           "params": {"name": "memory_aggregate", "arguments": a}}
    resp = server.dispatch(req, "memory")
    txt = resp["result"]["content"][0]["text"]
    m = re.search(r"=\s*(\d+)", txt)
    return (int(m.group(1)) if m else None), txt


QUESTIONS = [
    {"q": "雪莱（诗人）这个包里提到了多少个人物实体？",
     "unit": "persons", "scope": "人物/雪莱（诗人）"},
    {"q": "示例角色这个包涉及多少个地点？",
     "unit": "locations", "scope": "原创角色/示例角色"},
    {"q": "2026 年 3 月（按事件时间）收录了多少条记忆？",
     "unit": "packages", "dateprefix": "2026-03"},
    {"q": "整个记忆库里一共有多少个主题实体（topic）？",
     "unit": "topics"},
    {"q": "原创角色目录下一共有多少个事件包？",
     "unit": "packages", "scope": "原创角色"},
]

fails = []
print("=" * 70)
print("类型 8 计数 · 召回测试（gold=从 .md front-matter；答=真实 MCP 工具）")
print("=" * 70)
for item in QUESTIONS:
    g = gold(item["unit"], item.get("scope"), item.get("dateprefix"))
    g_n = len(g) if isinstance(g, set) else g
    ans, txt = tool(item["unit"], item.get("scope"), item.get("dateprefix"))
    passed = (ans == g_n)
    print(f"\n● {item['q']}")
    print(f"    gold(.md) = {g_n}   工具答 = {ans}   {'PASS' if passed else 'FAIL'}")
    if isinstance(g, set):
        print(f"    gold 枚举({len(g)}): {sorted(g)}")
    else:
        hits = sorted({d for d, _ in collect()
                       if (item.get('scope') is None or item['scope'] in d)
                       and (item.get('dateprefix') is None or
                            str(_.event_date or '').startswith(item['dateprefix']))})
        print(f"    gold 命中目录({len(hits)}): {hits}")
    print(f"    工具原文: {txt}")
    if not passed:
        fails.append(item["q"])

print("\n" + "=" * 70)
print("召回结果:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
print("=" * 70)
sys.exit(1 if fails else 0)
