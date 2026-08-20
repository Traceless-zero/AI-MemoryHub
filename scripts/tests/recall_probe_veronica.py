# -*- coding: utf-8 -*-
# 回归探针：定义意图（"X 是谁"）在「正式建档 + 专属锚点」人物上的召回。
# 关键发现（2026-08-19）：
#   - package_id 是【目录级】，veronica-base/origin/ext 三个文件共享同一
#     package_id='原创角色/维罗妮卡·夏·雪莱'（都在该目录下），不是各自独立的
#     层级路径。scoped 检索只能收敛到目录子树，不能收敛到单个 .md 文件。
#   - 对比霍华德（配角、无建档、无专属锚点）只能回 summary 撞运气，维罗妮卡
#     有「维罗妮卡是谁」专属锚点，query_anchors 能精确落点（TOP1 score 835+）。
import sys, json
sys.path.insert(0, r"E:\BaiduNetdiskDownload\项目\AIMH")
from hma.hma_core import Memory

ROOT = r"E:\BaiduNetdiskDownload\项目\AIMH\memory"
m = Memory(ROOT)
# 用法：python recall_probe_veronica.py "雪莱是谁"
# scope 永远指向 md 文件的【父级目录】（package 目录），不是 md 文件本身。
Q = sys.argv[1] if len(sys.argv) > 1 else "维罗妮卡是谁"
SCOPE = "原创角色/维罗妮卡·夏·雪莱"  # 真实目录级 package_id（veronica-base/origin/ext 的父目录）


def show_anchors(rows, label):
    print(f"  → {len(rows)} 条命中（pid 为短名；目录级 package_id={SCOPE!r} 含 base/origin/ext 三文件）")
    for i, (pid, anchor_title, about, chapter, score) in enumerate(rows, 1):
        print(f"  {i:2d}. [{score:.1f}] {pid}  | Chapter={chapter!r}")
        print(f"       about: {about[:80]}")


print("=" * 70)
print(f"[1] m.query('{Q}', top_k=6)  —— 包级 BM25（summary 落点校验门）")
print("=" * 70)
for i, (pid, title, summary, score) in enumerate(m.query(Q, top_k=6), 1):
    print(f"{i:2d}. [{score:.1f}] {pid}  | summary前40字: {summary[:40]}")

print()
print("=" * 70)
print(f"[2] m.query_anchors('{Q}', top_k=20)  —— 全局锚点级 BM25（定义意图入口）")
print("=" * 70)
show_anchors(m.query_anchors(Q, top_k=20), "global")

print()
print("=" * 70)
print(f"[3] m.query_anchors('{Q}', package_id={SCOPE!r}, top_k=20)  —— scope-first 收敛到维罗妮卡子树")
print("=" * 70)
show_anchors(m.query_anchors(Q, top_k=20, package_id=SCOPE), "scoped")

print()
print("=" * 70)
print(f"[4] m.resolve_query('{Q}', top_k=6)  —— 整链路（歧义门+拒答层+落点校验）")
print("=" * 70)
try:
    res = m.resolve_query(Q, top_k=6)
    print(json.dumps(res, ensure_ascii=False, indent=2)[:4000])
except Exception as e:
    print("resolve_query 抛错：", repr(e))
