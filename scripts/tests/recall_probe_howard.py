# -*- coding: utf-8 -*-
import sys, json
sys.path.insert(0, r"E:\BaiduNetdiskDownload\项目\AIMH")
from hma.hma_core import Memory

ROOT = r"E:\BaiduNetdiskDownload\项目\AIMH\memory"
m = Memory(ROOT)

Q = "霍华德是谁"

print("=" * 70)
print(f"[1] m.query('{Q}', top_k=8)  —— 包级 BM25")
print("=" * 70)
for i, (pid, title, summary, score) in enumerate(m.query(Q, top_k=8), 1):
    print(f"{i:2d}. [{score:.1f}] {pid}")
    print(f"     title : {title}")
    print(f"     summary: {summary}")

print()
print("=" * 70)
print(f"[2] m.query_anchors('{Q}', top_k=8)  —— 锚点级 BM25（定义意图入口）")
print("=" * 70)
for i, (pid, anchor_title, about, chapter, score) in enumerate(m.query_anchors(Q, top_k=8), 1):
    print(f"{i:2d}. [{score:.1f}] {pid}  | Chapter={chapter!r}")
    print(f"     about: {about}")

print()
print("=" * 70)
print(f"[3] m.resolve_query('{Q}', top_k=8)  —— 整链路（歧义门+拒答层）")
print("=" * 70)
try:
    res = m.resolve_query(Q, top_k=8)
    print(json.dumps(res, ensure_ascii=False, indent=2)[:4000])
except Exception as e:
    print("resolve_query 抛错：", repr(e))
