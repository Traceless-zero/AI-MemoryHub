# -*- coding: utf-8 -*-
"""
覆盖门（coverage gate）生产回归锁。

覆盖门 = 澄清之前判『区分词能否唯一锁定候选』：
  区分词 = 查询 token 中仅命中 top-K 候选恰好 1 个者（如 纯净蓝 / 孤品 / 2005）。
  若全部区分词指向同一候选 → 直接唯一返回（跳过澄清）；否则回落歧义门。
软门（非硬 AND 过滤）→ 不误杀、不删空，守 anti-over-abstain。

沙箱原型 sandbox_test_coverage_gate.py 于 2026-08-20 验证（唯一召回 100% / 误杀 0 / paraphrase 安全），
回归生产后原型脚本已清理（memory_sandbox/ 一并删除），用例并入本回归锁。
生产实装：hma/hma_core.py resolve_query（_query_tokens + _coverage_gate，stage=coverage_gate）。
用例与沙箱原型对齐；『区分词检测范围 = 召回 top-K 池』（池内唯 1 候选含该词即区分词）。
"""
import os, sys

PROJ = r"E:\BaiduNetdiskDownload\项目\AIMH"
REAL = os.path.join(PROJ, "memory")
sys.path.insert(0, PROJ)
os.environ.setdefault("HMA_NO_GUI", "1")

from hma.hma_core import Memory


def run():
    m = Memory(REAL)
    try:
        # (query, expect_rid, expect_gate):
        #   expect_rid 非 None → 期望唯一返回该包（rid）；expect_gate=True → 还须 stage=coverage_gate。
        #   expect_rid=None → 期望不唯一锁定（回落澄清 clarify / 拒答 abstain，均不得唯一返回宝石包）。
        CASES = [
            ("纯净蓝+钻石", "cangqiong-zhilei", True),
            ("纯净蓝",      "cangqiong-zhilei", False),  # 无歧义直接 keyword return，同样唯一召回
            ("孤品 蓝钻",   "shengbaoluzhihuo", True),
            ("2005 蓝钻",   "shengbaoluzhihuo", True),   # 2005 在召回池内仅圣保罗之焰含（origin 已退出宝石 top-K）
            ("蓝+钻石",     None, False),               # 共享特征 → 无区分词 → 回落澄清
            ("钻石",        None, False),
            ("蓝钻",        None, False),
            ("布达佩斯 蓝钻", None, False),               # 布达佩斯两枚都有 → 无误杀
            ("纯蓝",        None, False),               # paraphrase 谁都不中 → 不触发（不删空）
            ("纯蓝+钻石",   None, False),
        ]
        fails = []
        for q, expect_rid, expect_gate in CASES:
            r = m.resolve_query(q, top_k=5)
            dec = r.get("decision")
            stage = r.get("stage")
            res = r.get("results") or []
            winner = res[0][0] if res else None
            gate_fired = (dec == "return" and stage == "coverage_gate")
            if expect_rid is not None:
                ok = (dec == "return" and winner == expect_rid
                      and (not expect_gate or gate_fired))
            else:
                ok = not (dec == "return" and winner in ("cangqiong-zhilei", "shengbaoluzhihuo"))
            if not ok:
                fails.append(q)
            print(f"[{'OK' if ok else 'FAIL'}] {q:12s} -> decision={dec:<8s} stage={stage:<14s} winner={str(winner):<20s} expect={expect_rid}{'(gate)' if expect_gate else ''}")
            if not ok:
                print(f"        detail: {r}")
        n = len(CASES) - len(fails)
        print(f"\nPASS {n}/{len(CASES)}" + ("" if not fails else f"  FAIL={fails}"))
        return 0 if not fails else 1
    finally:
        m.close()


if __name__ == "__main__":
    sys.exit(run())
