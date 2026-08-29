# -*- coding: utf-8 -*-
"""bench_aimh_internal_groups —— 规模强干扰下的两级召回基准（2026-08-29 重建版）。

出处：什么是AIMH系统.md §九 曾记录「规模树（1029 事件干扰）下两级召回
recall@5 ≈ 94%（2026-08-19）」，但原脚本已失传（复现入口断链）。本文件按
文档口径重建：真实库抽样作 gold + 合成强干扰规模树，对照
  · 两级路径：query() 锁包 → scoped query_anchors（V0.5 路径）
  · 全局路径：query_anchors 不锁包直接全局
测召回@k 与误拒，并记录规模下的引擎耗时。

强干扰设计（确定性，seed 固定）：
  · 干扰包正文/关键词全部取自高频泛词池两两组合（与真实包共享表面词）；
  · 每个 gold 额外生成 5 个「近名干扰」（共享 gold 主题词、仅后缀不同）。
全程在 TEMP 沙箱进行，不落生产 memory/。重建原则见 MEMORY.md §七（AI 流、沙箱优先）。

用法：
    python scripts/tests/bench_aimh_internal_groups.py            # 跑并清理
    python scripts/tests/bench_aimh_internal_groups.py --keep     # 保留沙箱供检查
"""
import argparse
import json
import os
import random
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from hma.hma_core import Memory  # noqa: E402

SEED = 20260829
SCALE_EVENTS = 1029
EVENTS_PER_PKG = 3
N_GOLDS = 16
NEAR_MISS_PER_GOLD = 5

POOL = ["系统", "设计", "用户", "数据", "接口", "测试", "文档", "会议", "需求", "记录",
        "摘要", "分析", "方案", "结构", "流程", "模块", "版本", "计划", "评审", "总结",
        "清单", "日志", "配置", "状态", "进度", "目标", "任务", "问题", "风险", "资源",
        "模板", "样式", "脚本", "索引", "缓存", "安全", "性能", "部署", "监控", "报告"]


def _write_pkg(root, rel_dir, pid, title, summary, topic_key, topic_variants, kw_pool, rng,
               topic_in_summary=True, topic_in_anchors=True):
    """写一个事件包（1 个 .md = 1 事件）。

    topic_in_summary/anchors=False 用于近名干扰：共享词只留在 title 与 topic dict
    （最小共享足迹），其余字段用泛词池——否则克隆回声会稳定压过 gold，基准失真。"""
    d = os.path.join(root, rel_dir)
    os.makedirs(d, exist_ok=True)
    kws = rng.sample(kw_pool, min(3, len(kw_pool)))
    if topic_in_anchors:
        kws = kws + [topic_key]
    anchors = [{"Chapter": "概述",
                "about": f"{title}的概述章节（干扰占位，特征词来自泛词池）",
                "keywords": kws}]
    if topic_in_summary:
        summary = summary
    fm = (
        "---\n"
        f"title: {json.dumps(title, ensure_ascii=False)}\n"
        f"summary: {json.dumps(summary, ensure_ascii=False)}\n"
        f"tags: {json.dumps(['干扰'], ensure_ascii=False)}\n"
        "linked: []\n"
        "person: []\n"
        'event_date: "—"\n'
        "location: []\n"
        f"topic: {json.dumps([{topic_key: topic_variants}], ensure_ascii=False)}\n"
        f"anchors: {json.dumps(anchors, ensure_ascii=False)}\n"
        "pkage_created: 2026-08-29\n"
        "pkage_updated: 2026-08-29\n"
        "---\n\n"
        f"# {title}\n\n## 概述\n\n"
        + "、".join(kw_pool[: rng.randint(4, 8)]) + "。\n"
    )
    io = open(os.path.join(d, pid + ".md"), "w", encoding="utf-8", newline="\n")
    io.write(fm)
    io.close()


def build_interference(sbx_memory, gold_topics, rng):
    """生成规模树：泛词组合包 + 每个 gold 的近名干扰。返回 (包数, 事件数)。"""
    n_pkg = n_evt = 0
    # 1) 泛词组合包（两两组合覆盖池，结构上镜像真实库的多事件包形态）
    combos = [(a, b) for i, a in enumerate(POOL) for b in POOL[i + 1:]]
    rng.shuffle(combos)
    need = SCALE_EVENTS // EVENTS_PER_PKG
    for i, (a, b) in enumerate(combos[:need]):
        rel = f"干扰/群组{i // 12}/主题{i}"
        for e in range(EVENTS_PER_PKG):
            t = f"{a}{b}记录{e + 1}"
            _write_pkg(sbx_memory, rel, f"g{i}-{e}", t,
                       f"关于{a}与{b}的干扰记录{e + 1}。",
                       a, [b], POOL, rng)
            n_evt += 1
        n_pkg += 1
    # 2) 近名干扰：与 gold 共享「家族前缀」（实体首段），规范键互异且绝不包含
    #    gold 实体全串（超字符串会与 gold 同分 tiebreak）——即「战争与和平·卷一/卷二」
    #    形态：共享家族名、各有自己的判别词。共享词只留 topic 字段（字段对称）。
    for gi, (topic_key, _) in enumerate(gold_topics):
        family = topic_key.split()[0] if " " in topic_key else topic_key[:4]
        for k in range(NEAR_MISS_PER_GOLD):
            rel = f"干扰/近名/g{gi}"
            t = f"{rng.choice(POOL)}{rng.choice(POOL)}记录{k + 1}"
            _write_pkg(sbx_memory, rel, f"nm{gi}-{k}", t,
                       f"干扰记录{k + 1}。",
                       f"{family}相关{k}", [f"变体{k}"], POOL, rng,
                       topic_in_summary=False, topic_in_anchors=False)
            n_evt += 1
            n_pkg += 1
    return n_pkg, n_evt


def pick_golds(real_memory, rng, n):
    """从真实库确定性抽样 gold：按 id 排序后等距抽样。list_all_in_scope 返回 (rid,title,summary)。"""
    m = Memory(real_memory)
    try:
        rows = m.list_all_in_scope(top_k=None)
    finally:
        m.close()
    ids = sorted({r[0] for r in rows if isinstance(r, (tuple, list)) and r[0]})
    golds = []
    step = max(1, len(ids) // n)
    for i in range(0, len(ids), step):
        if len(golds) >= n:
            break
        golds.append(ids[i])
    return golds[:n]


def topic_token_of(memory_root, rid):
    """抽主题规范名：兼容 list[dict] / 裸 dict / list[str] 三种存储形态。"""
    m = Memory(memory_root)
    try:
        pkg = m.read(rid)
        t = pkg.topic
        keys = []
        if isinstance(t, dict):
            keys = list(t.keys())
        elif isinstance(t, (list, tuple)) and t:
            first = t[0]
            keys = list(first.keys()) if isinstance(first, dict) else (
                [first] if isinstance(first, str) else [])
        tok = keys[0] if keys else (pkg.title or rid)
        return tok, pkg
    finally:
        m.close()


def entity_tokens_of(memory_root, rid, cap=3):
    """模拟 AI 理解层的实体抽取：topic + person(+location) 规范名作为查询实体集。

    系统契约（MEMORY.md §八）：理解层必须**抽足实体**，多实体 coverage 叠加是
    消歧的正道——单 token 查询对同 topic 干扰必然同分，属违规的欠指定查询。
    """
    m = Memory(memory_root)
    try:
        pkg = m.read(rid)
        toks = []
        for field in (pkg.topic, pkg.person, pkg.location):
            if isinstance(field, dict):
                toks += list(field.keys())
            elif isinstance(field, list):
                for x in field:
                    if isinstance(x, dict):
                        toks += list(x.keys())
                    elif isinstance(x, str):
                        toks.append(x)
        out = []
        for t in toks:
            t = str(t).strip()
            if t and t not in out:
                out.append(t)
        return out[:cap] or [pkg.title or rid]
    finally:
        m.close()


def run_case(m, tokens, gold_pid, two_level, top_k=5):
    """返回 (hit@k 按 rank 计, 误拒 bool, 耗时 ms)。两级 = L1 锁包 → scoped L2。"""
    t0 = time.perf_counter()
    q = " ".join(tokens)
    abstain = False
    rank = None
    if two_level:
        r1 = m.query(q, keywords=tokens, top_k=top_k)
        pids = [x[0] for x in (r1 or [])]
        if not pids:
            abstain = True
        else:
            locked = pids[0]
            r2 = m.query_anchors(q, package_id=locked, keywords=tokens, top_k=top_k)
            rows = r2 if isinstance(r2, list) else (r2 or {}).get("results", [])
            if rows:
                rank = top_k + 1  # 锁包层命中与否由 L1 决定
                # 锚点层：gold 包的锚点出现在 scoped 结果即算命中
                if any(str(x[0]) == gold_pid for x in rows):
                    rank = 1
            else:
                rank = top_k + 1
        # L1 层的 rank 才是两级路径的包级召回
        rank = (pids.index(gold_pid) + 1) if gold_pid in pids else (top_k + 1)
    else:
        r = m.query_anchors(q, keywords=tokens, top_k=top_k)
        rows = r if isinstance(r, list) else (r or {}).get("results", [])
        if not rows:
            abstain = True
        pids = []
        for x in rows:
            pid = x[0] if isinstance(x, (tuple, list)) else x.get("package_id")
            if pid not in pids:
                pids.append(pid)
        rank = (pids.index(gold_pid) + 1) if gold_pid in pids else (top_k + 1)
    ms = (time.perf_counter() - t0) * 1000
    return rank, abstain, ms


def main():
    ap = argparse.ArgumentParser(description="规模强干扰两级召回基准（重建版）")
    ap.add_argument("--keep", action="store_true", help="保留沙箱供检查")
    a = ap.parse_args()

    rng = random.Random(SEED)
    real = os.path.join(REPO, "memory")
    sbx = os.path.join(os.environ.get("TEMP", "."), "aimh_scale_bench")
    if os.path.isdir(sbx):
        shutil.rmtree(sbx)
    os.makedirs(sbx)
    sbx_mem = os.path.join(sbx, "memory")
    shutil.copytree(real, sbx_mem)

    # gold 抽样（真实库）。⚠️ ID 空间归一：list_all_in_scope 返回复合路径 id，
    # 而 query/query_anchors 返回事件 id（文件名 stem）——gold 比较必须用 stem。
    golds = pick_golds(real, rng, N_GOLDS)
    cases = []
    for rid in golds:
        tok, _ = topic_token_of(real, rid)
        stem = os.path.splitext(os.path.basename(rid.replace("\\", "/")))[0]
        etoks = entity_tokens_of(real, rid)
        cases.append((stem, etoks, rid))
    print(f"gold 抽样：{len(cases)} 题（真实库确定性抽样，seed={SEED}）")

    # 规模树
    gold_topics = [(toks[0], None) for _, toks, _ in cases]
    n_pkg, n_evt = build_interference(sbx_mem, gold_topics, rng)
    print(f"干扰树：{n_pkg} 包 / {n_evt} 事件（泛词组合 + 每 gold {NEAR_MISS_PER_GOLD} 近名）")

    m = Memory(sbx_mem)
    t0 = time.perf_counter()
    cnt = m.rebuild_all()
    t_build = (time.perf_counter() - t0) * 1000
    print(f"沙箱索引重建：{cnt} 事件，{t_build:.0f} ms")

    res = {"two": {"r": [], "abstain": 0, "ms": []},
           "global": {"r": [], "abstain": 0, "ms": []}}
    detail = []
    for gold_pid, tokens, disp in cases:
        for name, two in (("two", True), ("global", False)):
            rank, abstain, ms = run_case(m, tokens, gold_pid, two)
            res[name]["r"].append(rank)
            res[name]["abstain"] += int(abstain)
            res[name]["ms"].append(ms)
        d_two = res["two"]["r"][-1]
        d_glb = res["global"]["r"][-1]
        detail.append((disp, tokens[0], d_two, d_glb))

    def recall_at(k, ranks):
        return sum(1 for r in ranks if r <= k) / len(ranks) * 100

    print("\n=== 规模强干扰结果（gold 抽样 %d 题，库 %d 事件）===" % (len(cases), cnt))
    print(f"{'路径':<10}{'recall@1':>10}{'recall@3':>10}{'recall@5':>10}{'误拒':>6}{'均耗时':>10}")
    for name, label in (("two", "两级"), ("global", "全局")):
        r = res[name]["r"]
        print(f"{label:<10}{recall_at(1, r):>9.1f}%{recall_at(3, r):>9.1f}%"
              f"{recall_at(5, r):>9.1f}%{res[name]['abstain']:>6}{sum(res[name]['ms'])/len(res[name]['ms']):>9.1f}ms")
    print("\n=== 逐题明细（rank>5 = 未召回）===")
    for disp, toks, d_two, d_glb in detail:
        flag = "" if (d_two <= 5) else "  ← 两级未召回"
        print(f"  gold={disp.split('/')[-1].split(chr(92))[-1][:24]:<26} 实体={str(toks)[:18]:<20} 两级@{d_two} 全局@{d_glb}{flag}")

    m.close()
    if a.keep:
        print(f"\n沙箱保留：{sbx}")
    else:
        shutil.rmtree(sbx)
        print("\n(沙箱已清理)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
