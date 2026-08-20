# -*- coding: utf-8 -*-
"""D1+D2 功能验证：memory_resolve 接入 + REFINE + 经 resolver 的 corpus_missing_entity 拒答。

不依赖 LLM：REFINE 用零-ML 同义词词典兜底（hma.refine.dict_refine_decomposer）。
跑法：python scripts/tests/test_resolve_refine.py
"""
import os
import sys

PROJECT = r"E:\BaiduNetdiskDownload\项目\AIMH"
sys.path.insert(0, PROJECT)

from hma import server as S
from hma.hma_core import Memory
from hma.refine import dict_refine_decomposer

ROOT = os.path.join(PROJECT, "memory")
m = Memory(ROOT)

passed, failed = [], []

def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  — {detail}" if detail and not cond else ""))

print("=== D2a · memory_resolve 经 MCP handler 跑通（多跳+歧义门）===")
# 单跳域内题：应返回候选而非报错
out1 = S._h_resolve(ROOT, {"q": "维罗妮卡", "mode": "single", "keywords": ["维罗妮卡"], "top_k": 5})
check("memory_resolve 单跳返回非空结果", "[" in out1 and "维罗妮卡" in out1, out1[:60])
# 多跳：沿 linked BFS 扩簇后跑歧义门
out2 = S._h_resolve(ROOT, {"q": "圣保罗之焰", "mode": "single", "top_k": 5, "multihop": True})
check("memory_resolve multihop 返回非空结果", bool(out2) and "(no match)" not in out2, out2[:60])

print("=== D1 · 经 resolver 的 corpus_missing_entity 硬拒答 ===")
# 域外复合实体，AI 传 keywords → resolver 应拒答
out3 = S._h_resolve(ROOT, {"q": "魔改记忆引擎是什么", "mode": "single",
                           "keywords": ["魔改记忆引擎"]})
check("resolver 对域外 keywords 拒答(corpus_missing_entity)",
      "ABSTAIN: corpus_missing_entity" in out3, out3[:80])
# 对照：不传 keywords（纯机械路径）→ 不应触发硬拒答（已知弱点，静默漏）
out4 = S._h_resolve(ROOT, {"q": "魔改记忆引擎是什么", "mode": "single"})
check("resolver 无 keywords 时不走硬拒答（机械兜底，符合设计）",
      "ABSTAIN: corpus_missing_entity" not in out4, out4[:60])

print("=== D2b · REFINE 零-ML 兜底：最值钱 → 宝石 → 圣保罗之焰 ===")
kw = dict_refine_decomposer(m, "她人生里最值钱的一次得手是什么")
check("dict_refine 把『最值钱』扩到『宝石』", "宝石" in kw, str(kw[:8]))
# 裸查询（无 REFINE）vs REFINE 注入：圣保罗之焰（宝石）应被抬升
raw = m.query_anchors("她人生里最值钱的一次得手是什么", top_k=5)
raw_ids = [r[0] for r in raw]
refined = m.query_anchors("她人生里最值钱的一次得手是什么",
                          top_k=5, decomposer=dict_refine_decomposer)
refined_ids = [r[0] for r in refined]
print("    裸查 top1:", (raw_ids[0] if raw_ids else None))
print("    REFINE top1:", (refined_ids[0] if refined_ids else None))
check("REFINE 把『圣保罗之焰』抬进 top5",
      any("veronica-origin" == rid for rid in refined_ids), str(refined_ids[:3]))

print("=== D1 · keywords 透传 _h_query_anchors ===")
out5 = S._h_query_anchors(ROOT, {"q": "魔改记忆引擎是什么", "mode": "single",
                                 "keywords": ["魔改记忆引擎"]})
check("keywords 透传至 query_anchors 且拒答", "ABSTAIN" in out5, out5[:60])

print("\n========================================")
print(f"通过 {len(passed)} / 失败 {len(failed)}")
if failed:
    print("失败项：", failed)
    sys.exit(1)
print("ALL GREEN ✅")
