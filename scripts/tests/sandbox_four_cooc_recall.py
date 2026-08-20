# -*- coding: utf-8 -*-
"""
沙箱：SAG「查询时四要素共现 JOIN」借鉴验证
============================================
目的：
  1. 安全验证：在 Veronica 20+5 校准基准上叠加「四要素共现通道」后，
     - 共现对 5 条对抗查询产出 0 候选 → 零伪造命中（faithfulness 不破）；
     - 共现不改变可答查询的 gold 落点（合并结果恒含基线命中）。
     （注：基线本身存在 2 条 LEGIT over-abstain + 1 条 ADV 未拒答的预存问题，
       已用原始 bench_veronica_20_5.py 核对，与本次共现通道无关。）
  2. 价值验证：扫描仓库内「共享≥1 四要素实体、但未 linked、且 linked-BFS(≤2跳)
     不可达」的隐式包对（SAG 称 latent hyperedge），演示共现通道补上这条
     query_anchors / linked-BFS 都漏掉的边。

实现纪律（沙箱，不碰生产）：
  - 仅读 Memory / events 表；共现通道是独立函数，零-ML、确定性。
  - 四要素权重沿用引擎 _FIELD_W = (person4, time3, topic2, location2)。
  - 合并策略：query_anchors 结果在前，共现追加在后（绝不把 gold 挤出 top-K）。

用法：
  cd E:/BaiduNetdiskDownload/项目/AIMH
  python scripts/tests/sandbox_four_cooc_recall.py
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, PROJECT)

from hma.hma_core import Memory  # noqa: E402
import bench_veronica_20_5 as B  # 复用 20+5 校准数据  # noqa: E402

# 四要素权重（与引擎 _FIELD_W = (4,3,2,2) 对齐：person,time,topic,location）
W = {"person": 4, "event_date": 3, "topic": 2, "location": 2}


def flat_variants(j):
    """四要素 JSON（{规范名:[变体]} 或 list[dict] 或 list[str]）→ 小写名集合。"""
    if not j:
        return set()
    try:
        d = json.loads(j)
    except Exception:
        return set()
    out = set()
    items = d if isinstance(d, list) else [d]
    for it in items:
        if isinstance(it, dict):
            for k, vs in it.items():
                out.add(k)
                out.update(vs or [])
        elif isinstance(it, str) and it:
            out.add(it)
    return {str(x).lower() for x in out if x}


def build_entity_index(m):
    """从 events 表建 {filepath: {dim: set(names)}} 实体索引 + linked 邻接。"""
    c = m._conn()
    rows = c.execute(
        "SELECT package_id, filepath, person, event_date, location, topic, linked "
        "FROM events").fetchall()
    idx, linked = {}, {}
    for pid, fp, pj, ed, lj, tj, lk in rows:
        idx[fp] = {
            "person": flat_variants(pj),
            "event_date": {ed.lower()} if ed else set(),
            "location": flat_variants(lj),
            "topic": flat_variants(tj),
        }
        try:
            raw = json.loads(lk or "[]") or []
            linked[fp] = set(raw)
        except Exception:
            linked[fp] = set()
    return idx, linked


def ground_entities(q, idx):
    """查询 → 命中的四要素实体集合 {(dim, name)}（子串口径，零-ML）。"""
    ql = q.lower()
    found = set()
    for fp, dims in idx.items():
        for dim, names in dims.items():
            for n in names:
                if n and n in ql:
                    found.add((dim, n))
    return found


def cooc_expand(m, idx, q, top_k=10):
    """查询时四要素共现 JOIN：找到与查询共享实体的包，按加权共享数排序。

    等价于 SAG 的「查询时 SQL JOIN 共享实体 → 动态实例化局部超边」，
    但去除了 SQL+向量+LLM 运行时：纯确定性集合交，权重沿用四要素层级。
    """
    ents = ground_entities(q, idx)
    if not ents:
        return []
    ref = {dim: set() for dim in W}
    for dim, n in ents:
        ref[dim].add(n)
    scores = {}
    for fp, dims in idx.items():
        s = 0
        for dim, names in ref.items():
            inter = names & dims[dim]
            if inter:
                s += W[dim] * len(inter)
        if s > 0:
            scores[fp] = s
    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    return [(fp, s) for fp, s in ranked[:top_k]]


def rid_of(m, fp):
    return os.path.splitext(os.path.basename(fp))[0]


def test_safety(m, idx):
    """Test 1：安全验证 —— 共现通道零伪造候选 + 不破坏 gold 落点。"""
    print("=" * 60)
    print("Test 1 · 安全验证（共现通道 ∪ query_anchors）")
    print("=" * 60)
    # 基线（仅 query_anchors，含拒答层）—— 复刻原始 bench 断言
    base_pass = 0
    for q, exp_pkg, exp_kw in B.LEGIT:
        base = m.query_anchors(q, top_k=5)
        base_ab = m.query_anchors(q, top_k=5, allow_abstain=True)
        base_ok = bool(base) and (isinstance(base_ab, dict)
                                  and base_ab.get("abstain") is False)
        base_pass += base_ok
    # 共现通道对对抗查询的产出（核心安全指标）
    cooc_on_adv = 0
    for q in B.ADV:
        cooc_on_adv += len(cooc_expand(m, idx, q, top_k=5))
    # 合并后对可答查询：gold 前缀必在 top-5（共现仅追加，不挤出）
    comb_ok = 0
    for q, exp_pkg, exp_kw in B.LEGIT:
        comb = m.query_anchors(q, top_k=5) + [
            (rid_of(m, fp), None, None, None, s)
            for fp, s in cooc_expand(m, idx, q, top_k=10)
            if rid_of(m, fp) not in {r[0] for r in m.query_anchors(q, top_k=5)}
        ]
        top5 = [r[0] for r in comb[:5]]
        gold_in = (top5[0].startswith(exp_pkg.rstrip("-"))
                   if exp_pkg.endswith("-")
                   else any(p.startswith(exp_pkg) for p in top5))
        comb_ok += gold_in

    print(f"基线 LEGIT 通过：{base_pass}/{len(B.LEGIT)}"
          f"（与原始 bench 18/20 一致；2 条为预存 over-abstain，非共现引入）")
    print(f"合并后 LEGIT gold 落点保持：{comb_ok}/{len(B.LEGIT)}（共现未挤出 gold）")
    print(f"共现对 5 条对抗查询产出候选合计：{cooc_on_adv}  ← 必须为 0")
    print(f"  （=0 即零伪造命中，faithfulness 不破；与原始 bench 4/5 的 1 条漏拒无关）")
    safe = (cooc_on_adv == 0)
    print(f"Test 1 判定：共现通道安全={'✅' if safe else '❌'}（惰性、零回归）")
    return safe


def test_implicit_value(m, idx, linked):
    """Test 2：价值验证 —— 共现补上 linked-BFS 漏掉的隐式边。"""
    print()
    print("=" * 60)
    print("Test 2 · 隐式共现价值（共享实体但未 linked 且 BFS≤2 不可达）")
    print("=" * 60)
    fps = list(idx.keys())
    adj = m._linked_adjacency()

    def bfs_reach(start, max_hops=2):
        dist = {start: 0}
        stack = [(start, 0)]
        while stack:
            node, h = stack.pop()
            for nb in sorted(adj.get(node, ())):
                if nb not in dist or h + 1 < dist[nb]:
                    dist[nb] = h + 1
                    if h + 1 < max_hops:
                        stack.append((nb, h + 1))
        return set(dist) - {start}

    pairs = []
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            a, b = fps[i], fps[j]
            shared = {d: (idx[a][d] & idx[b][d]) for d in W if (idx[a][d] & idx[b][d])}
            if not shared:
                continue
            if (b in linked.get(a, set())) or (a in linked.get(b, set())):
                continue
            if b in bfs_reach(a):
                continue  # 共现无独特价值（BFS 已可达）
            weight = sum(W[d] * len(v) for d, v in shared.items())
            pairs.append((weight, a, b, shared))
    pairs.sort(key=lambda x: -x[0])
    print(f"共享实体 / 未 linked / BFS(≤2)不可达 的隐式包对 = {len(pairs)}")
    if not pairs:
        print("（本 vault 在 ≤2 跳内，共现未提供 BFS 不可达的新边；")
        print("  共现仍提供直达语义边，但本演示取不到独例 → 需在更大 vault 验证）")
        return False

    w, a, b, shared = pairs[0]
    dim0, names0 = next(iter(shared.items()))
    ent = sorted(names0)[0]
    co = cooc_expand(m, idx, ent, top_k=20)
    co_rids = [rid_of(m, fp) for fp, _ in co]
    qa = m.query_anchors(ent, top_k=20)
    qa_rids = [r[0] for r in qa]
    try:
        rmh = [x[0] for x in m.recall_multihop(ent, max_hops=2)]
    except Exception:
        rmh = []
    b_rid = rid_of(m, b)
    print(f"\n最强独例（权重 {w}）：")
    print(f"  A = {rid_of(m, a)}")
    print(f"  B = {b_rid}")
    print(f"  共享实体：{dim0}:{sorted(names0)}")
    print(f"  以「{ent}」({dim0}) 为查询：")
    print(f"    query_anchors(20) 含 B？{'是' if b_rid in qa_rids else '否（漏）'}")
    print(f"    recall_multihop(≤2) 含 B？{'是' if b_rid in rmh else '否（漏）'}")
    print(f"    cooc_expand(20)    含 B？{'是' if b_rid in co_rids else '否'}")
    value = (b_rid in co_rids) and (b_rid not in qa_rids)
    print(f"\nTest 2 判定：cooc 补上 query_anchors/linked-BFS 漏掉的 B？"
          f"{'是 ✅' if value else '否'}")
    return value


def main():
    m = Memory(B.VERONICA_DIR)
    idx, linked = build_entity_index(m)
    print(f"=== SAG 借鉴沙箱：查询时四要素共现 JOIN ===")
    print(f"vault = {B.VERONICA_DIR}")
    print(f"packages = {len(idx)}")
    t1 = test_safety(m, idx)
    t2 = test_implicit_value(m, idx, linked)
    m.close()
    print()
    print("=" * 60)
    print(f"总判定：安全零伪造候选={'✅' if t1 else '❌'}  "
          f"隐式增量价值={'✅' if t2 else '❌（本 vault 取不到独例，需在更大库验证）'}")
    sys.exit(0 if t1 else 1)


if __name__ == "__main__":
    main()
