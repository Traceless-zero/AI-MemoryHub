"""诊断：query_anchors 过度拒答的根因（_relevance_filter vs 锚点打分）。"""
import sys, os
sys.path.insert(0, r"E:/BaiduNetdiskDownload/项目/AIMH")
from hma.hma_core import Memory

ROOT = r"E:/BaiduNetdiskDownload/项目/AIMH/memory"
m = Memory(ROOT)

print("=== query_anchors(allow_abstain=False) 是否真命中（过滤前）===")
for q in ["黄蓝色的宝石", "蓝钻", "红楼梦的作者是谁", "今天天气怎么样"]:
    hits = m.query_anchors(q, top_k=3, allow_abstain=False)
    print(f"[q={q!r}] no_abstain top3=", [(x[0], (x[1] or '')[:14], round(x[4], 2)) for x in hits[:3]])

print("\n=== _understand_query 拆出的 terms + 各 term idf ===")
for q in ["黄蓝色的宝石", "蓝钻"]:
    terms = m._understand_query(q)
    print(f"[q={q!r}] terms={terms}")
    for t in terms:
        print(f"    idf({t!r}) = {m._idf(t):.3f}")
    w_total = sum(m._idf(t) for t in terms)
    print(f"    w_total={w_total:.3f}  thr(0.5*w_total)={0.5*w_total:.3f}")
