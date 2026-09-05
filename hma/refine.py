# -*- coding: utf-8 -*-
"""refine —— REFINE 机制的机械侧组件
================================================

当前仅含：**机械兜底拒答闸**（方向 4 · 语料零共现检测，`corpus_overlap_absent`）——
查询与语料零共现 → 最外国语料 → 拒答；零依赖、域自适应的安全网。

语义桥接（REFINE 本体：表层词 → 语料主题词）**归驱动理解层**——AI 流
（NL→实体词→per-entity query）即转述桥接；LLM 桥接的注入点为 `query` /
`resolve_query` 的 `decomposer=` 参数（设计见 召回消歧管线设计（实现）.md §14.3）。
引擎自身零-ML，不做语义匹配、不维护手写桥接词典。
"""

# ─────────────────────────────────────────────────────────────────────────
# 方向 4 · 机械兜底拒答闸（语料零重叠）
# ─────────────────────────────────────────────────────────────────────────
# 设计边界（务必先读）：纯机械子串/二元匹配对「量子计算」类复合实体**不可达**——
# 它含子词「计算」在语料里（可计算/计算），故任何子串闸都对「量子计算」失效。
# 只有「知道量子计算是个整体词」（jieba 或 AI keywords 接口）才能拒。因此本闸
# 只抓**与语料零共现**的最外国语料（太阳系/红烧肉/珠穆朗玛峰/鲁迅故乡类），
# 是零依赖、域自适应的安全网；复合实体域外题仍由 AI keywords 接口兜。
import re as _re
import json as _json

_CJK = _re.compile(r"[\u4e00-\u9fff]+")
_LAT = _re.compile(r"[A-Za-z0-9\-]+")


def _cjk_runs(s):
    return _CJK.findall(s or "")


def _feed_grams(freq, text, max_len):
    for run in _cjk_runs(text):
        n = len(run)
        for L in range(2, min(max_len, n) + 1):
            for i in range(n - L + 1):
                g = run[i:i + L]
                freq[g] = freq.get(g, 0) + 1


def _feed_obj(freq, obj, max_len):
    if isinstance(obj, dict):
        for k, vs in obj.items():
            _feed_grams(freq, k, max_len)
            if isinstance(vs, list):
                for v in vs:
                    _feed_grams(freq, v, max_len)
    elif isinstance(obj, list):
        for it in obj:
            if isinstance(it, str):
                _feed_grams(freq, it, max_len)
            elif isinstance(it, dict):
                # 锚点 dict：Chapter/about/summary/title + keywords/tags 都喂，
                # 实体常活在 about 自由文本（如「完美超级士兵血清」在 about 里）。
                for kk in ("Chapter", "about", "title", "summary"):
                    if it.get(kk):
                        _feed_grams(freq, it[kk], max_len)
                for kk in ("keywords", "tags"):
                    for v in (it.get(kk) or []):
                        _feed_grams(freq, v, max_len)


def build_corpus_vocab(memory, max_len=4, min_freq=1):
    """从语料自身抽多字词典（零依赖、域自适应）。

    收集 title / summary / 四要素 canonical+变体 / 锚点(Chapter+about+keywords) 中的
    2..max_len 字 CJK n-gram 与 latin≥2 词。用于机械兜底路径的「零共现」拒答判定。

    ⚠️ 不喂 raw body：body 含大量「算的/的最」等垃圾二元，会污染 foothold 让域外题
    漏检；实体足以由其 about/keywords/四要素覆盖。min_freq=1（域内题的判别词必在
    词典 → 必有共现 → 不误拒；域外最外国语料零共现 → 拒答）。
    """
    freq = {}
    conn = memory._conn()
    try:
        rows = conn.execute(
            "SELECT title, summary, person, location, topic, anchors "
            "FROM events").fetchall()
    except Exception:
        return set()
    for title, summary, person, location, topic, anchors in rows:
        _feed_grams(freq, title, max_len)
        _feed_grams(freq, summary, max_len)
        for col in (person, location, topic, anchors):
            if not col:
                continue
            try:
                obj = _json.loads(col)
            except Exception:
                obj = None
            if obj is not None:
                _feed_obj(freq, obj, max_len)
            else:
                _feed_grams(freq, col, max_len)
        # latin 词（如 AIMH / 示例代号 / 2022）
        for col in (title, summary, person, location, topic, anchors):
            if not col:
                continue
            for tok in _LAT.findall(col):
                t = tok.lower()
                if len(t) >= 2:
                    freq[t] = freq.get(t, 0) + 1
    return {g for g, c in freq.items() if c >= min_freq}


def _query_runs(q):
    out = list(_cjk_runs(q))
    for tok in _LAT.findall(q):
        out.append(tok.lower())
    return out


def has_corpus_overlap(q, vocab, max_len=4):
    """查询与语料是否有 ≥2 字 CJK 共现 / latin≥2 词共现。True=有 foothold。"""
    for run in _query_runs(q):
        if _LAT.match(run):
            if run in vocab:
                return True
            continue
        n = len(run)
        for L in range(2, min(max_len, n) + 1):
            for i in range(n - L + 1):
                if run[i:i + L] in vocab:
                    return True
    return False


def corpus_overlap_absent(memory, q, max_len=4):
    """机械拒答辅助：查询与语料是否零共现。True=零共现（应拒答）。

    词典缓存在 memory._vocab_cache（首次构建后复用，避免每次查询全表扫）。
    """
    cache = getattr(memory, "_vocab_cache", None)
    if cache is None:
        cache = build_corpus_vocab(memory, max_len=max_len)
        try:
            memory._vocab_cache = cache
        except Exception:
            pass
    return not has_corpus_overlap(q, cache, max_len)

