# -*- coding: utf-8 -*-
"""D2 回归锁：AI keywords 接口下对抗题 5/5 硬拒（2026-08-19 用户拍板）。

背景：鲁迅《故乡》在【机械路径】下漏拒（G7 已知弱点，机械拆词不可靠）。
用户拍板：只用 AI 流程（keywords/decomposer 接口）启用 corpus_missing_entity
硬拒闸，机械流程不动（"水多加码的麻烦事"）。

验证：query_anchors(q, allow_abstain=True, keywords=[AI解析词]) 下——
  · 对抗 5 条 → abstain=True（empty_pool 或 corpus_missing_entity，效果等价）
  · 域内 3 条 → abstain=False 正常命中（无误拒）
"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, PROJECT)

from hma.hma_core import Memory
from scripts.tests.bench_veronica_20_5 import VERONICA_DIR

# AI 理解层解析出的判别复合词（模拟）
ADV_AI = [
    ("鲁迅的小说《故乡》讲的是什么", ["鲁迅", "故乡"]),
    ("量子计算的最新发展是什么", ["量子计算"]),
    ("苹果公司今天的股价是多少", ["苹果公司", "股价"]),
    ("2022年世界杯冠军是谁", ["世界杯", "冠军"]),
    ("番茄炒蛋怎么做才好吃", ["番茄炒蛋"]),
]
LEGIT_AI = [
    ("圣保罗之焰是什么", ["圣保罗之焰"]),
    ("协议X-2是什么", ["协议X-2"]),
    ("午夜魅影是谁", ["午夜魅影"]),
]


def main():
    m = Memory(VERONICA_DIR)
    adv_pass = 0
    for q, kw in ADV_AI:
        res = m.query_anchors(q, top_k=5, allow_abstain=True, keywords=kw)
        abstain = isinstance(res, dict) and res.get("abstain") is True
        adv_pass += abstain
        print(f"[{'PASS' if abstain else 'FAIL'}] 对抗: {q}  -> abstain={abstain} "
              f"reason={res.get('reason','') if isinstance(res,dict) else '?'}")
    legit_pass = 0
    for q, kw in LEGIT_AI:
        res = m.query_anchors(q, top_k=5, allow_abstain=True, keywords=kw)
        no_abstain = isinstance(res, dict) and res.get("abstain") is False
        legit_pass += no_abstain
        hits = len(res.get("answer", [])) if isinstance(res, dict) else 0
        print(f"[{'PASS' if no_abstain else 'FAIL'}] 域内: {q}  -> 未误拒={no_abstain} hits={hits}")
    print(f"\n结果：对抗 {adv_pass}/{len(ADV_AI)} 硬拒（要求 5/5）；域内 {legit_pass}/{len(LEGIT_AI)} 无误拒（要求 3/3）")
    return 0 if (adv_pass == len(ADV_AI) and legit_pass == len(LEGIT_AI)) else 1


if __name__ == "__main__":
    sys.exit(main())
