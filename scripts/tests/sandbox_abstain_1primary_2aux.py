# -*- coding: utf-8 -*-
"""
沙箱：拒答规则 "① 覆盖门为主 / ② 单词逃逸闸为辅" 验证
========================================================
设计（用户 2026-08-19 拍板）：
  · 判别词 disc_terms = 四要素规范名 + 查询 CJK 内容词(_reform_terms)
    —— 剔除变体特征值(如 圣保罗之焰 的 黄/橙/蓝/双色/宝石/价值连城)。
  · 召回词 terms(原 full keys) 留给 BM25，不变。
  · _relevance_filter / _abstain 的阈值与覆盖都改吃 disc_terms；
    ① rel>=thr(覆盖门) 与 ② max(match)>=floor(逃逸闸) 逻辑原样保留——
    干净词表下 ② 不会被稀有变体顶高，自然退为 ① 的辅助安全网。

零-ML 确定性，不落生产；纯 monkeypatch 在进程内验证行为差异。
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, PROJECT)

import hma.hma_core as H
from hma.hma_core import Memory
from scripts.tests.bench_veronica_20_5 import LEGIT, ADV, VERONICA_DIR

GATE = H._GROUND_PKG_GATE


def _understand_query_patch(self, q, context=None):
    """返回原 full keys(BM25 召回不变)，并把干净判别词存到 self._disc_terms。"""
    ql = (q + " " + (context or "")).lower()
    c = self._conn()
    rows = c.execute(
        "SELECT person,topic,event_date,location,tags FROM events").fetchall()
    canon = []
    seen_c = set()
    for person_j, topic_j, edate, loc_j, tags_j in rows:
        for col in (person_j, topic_j, loc_j):
            d = json.loads(col or "{}") if col else {}
            items = [d] if isinstance(d, dict) else (d if isinstance(d, list) else [])
            for item in items:
                if isinstance(item, dict):
                    nm = item
                elif isinstance(item, str) and item:
                    nm = {item: []}
                else:
                    continue
                for canon_name, variants in nm.items():
                    names = [canon_name] + list(variants or [])
                    if any(n and n.lower() in ql for n in names):
                        if (self._pkg_freq(canon_name) < GATE
                                and canon_name not in seen_c):
                            seen_c.add(canon_name)
                            canon.append(canon_name)
    reform = H._reform_terms(q)
    disc = []
    seen_d = set()
    for t in canon + list(reform):
        if t and t not in seen_d:
            seen_d.add(t)
            disc.append(t)
    self._disc_terms = disc
    return self._orig_understand_query(q, context)


def _relevance_filter_patch(self, scored, terms, theta=0.5):
    return self._orig_relevance_filter(scored, self._disc_terms, theta)


def _abstain_patch(self, scored, q, terms, top_k, kappa, pid=None,
                   entity_gate=False):
    return self._orig_abstain(scored, q, self._disc_terms, top_k, kappa,
                              pid, entity_gate)


def apply_patches():
    Memory._orig_understand_query = Memory._understand_query
    Memory._understand_query = _understand_query_patch
    Memory._orig_relevance_filter = Memory._relevance_filter
    Memory._relevance_filter = _relevance_filter_patch
    Memory._orig_abstain = Memory._abstain
    Memory._abstain = _abstain_patch


def run_bench(m):
    legit_pass = 0
    adv_pass = 0
    legit_detail = []
    adv_detail = []
    for q, exp_pkg, exp_kw in LEGIT:
        hits = m.query_anchors(q, top_k=5)
        ab = m.query_anchors(q, top_k=5, allow_abstain=True)
        list_ok = bool(hits)
        no_abstain = isinstance(ab, dict) and ab.get("abstain") is False
        ok = list_ok and no_abstain
        legit_pass += ok
        top = hits[0] if hits else None
        top_pid = (top[0] if isinstance(top, (tuple, list)) else None) if top else ""
        top_title = (top[1] if isinstance(top, (tuple, list)) else None) if top else ""
        kw_ok = (exp_kw == "" or (exp_kw in (top_title or "")))
        pkg_ok = top_pid.startswith(exp_pkg)
        legit_detail.append((q, "PASS" if ok else "FAIL",
                             ab.get("abstain") if isinstance(ab, dict) else "n/a",
                             ab.get("reason") if isinstance(ab, dict) else "?",
                             f"{top_pid}/{top_title}",
                             "✓" if (pkg_ok and kw_ok) else "⚠"))
    for q in ADV:
        ab = m.query_anchors(q, top_k=5, allow_abstain=True)
        abstain = isinstance(ab, dict) and ab.get("abstain") is True
        adv_pass += abstain
        adv_detail.append((q, "PASS" if abstain else "FAIL",
                           ab.get("reason") if isinstance(ab, dict) else "?"))
    return legit_pass, adv_pass, legit_detail, adv_detail


def case_detail(m, q):
    ab = m.query_anchors(q, top_k=5, allow_abstain=True)
    hits = m.query_anchors(q, top_k=5)
    disc = getattr(m, "_disc_terms", [])
    st = ab.get("abstain") if isinstance(ab, dict) else "n/a"
    reason = ab.get("reason") if isinstance(ab, dict) else "?"
    top = (hits[0][0] if hits and isinstance(hits[0], (tuple, list))
           else (hits[0].get("package_id") if hits else "?")) if hits else "无命中"
    return f"  q={q!r}\n    disc_terms={disc}\n    verdict={st} reason={reason}\n    top={top}"


def main():
    print("########## 基线（无补丁，当前生产行为）##########")
    m0 = Memory(VERONICA_DIR)
    bl_legit, bl_adv, _, _ = run_bench(m0)
    print(f"  可答基线：{bl_legit}/{len(LEGIT)}   对抗基线：{bl_adv}/{len(ADV)}")
    print("  三处重点用例（基线）：")
    for q in ["圣保罗之焰", "协议X-2", "鲁迅的小说《故乡》讲的是什么"]:
        print(case_detail(m0, q))
    m0.close()

    print("\n########## 补丁后（① 覆盖门为主 / ② 逃逸闸为辅）##########")
    m1 = Memory(VERONICA_DIR)
    apply_patches()
    pt_legit, pt_adv, _, _ = run_bench(m1)
    print(f"  可答补丁后：{pt_legit}/{len(LEGIT)}   对抗补丁后：{pt_adv}/{len(ADV)}")
    print("  三处重点用例（补丁后）：")
    for q in ["圣保罗之焰", "协议X-2", "鲁迅的小说《故乡》讲的是什么"]:
        print(case_detail(m1, q))
    m1.close()

    print("\n########## 差异总结 ##########")
    print(f"  可答：{bl_legit} -> {pt_legit}  (Δ={pt_legit-bl_legit})")
    print(f"  对抗：{bl_adv} -> {pt_adv}  (Δ={pt_adv-bl_adv})")
    print("  圣保罗之焰/协议X-2 应从 over-abstain(FAIL) 翻 PASS；")
    print("  鲁迅《故乡》为 G7 已知弱点(漏拒)，本改动不触及，应维持原样。")


if __name__ == "__main__":
    main()
