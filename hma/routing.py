# -*- coding: utf-8 -*-
"""AIMH 公共路由层（确定性、零-ML）。

把「查询 → 包 / 作用域」的路由决策从 hma_core 抽出为**单一真相源**，供引擎
（query_anchors 缩圈）与理解层（aimh-recall 技能 v3）共用，消除
「代码层路由表」与「技能自然语言路由」两套说法的漂移。

## 判别式的来源：结构性，而非手写关键词表

判别词**结构性来自记忆根的目录名（package_id 末段）+ 包标题 + 各包锚点 keywords**，
由 DB 中真实存在的 `package_id` 集合约束（见 `resolve_scope(..., valid_pids, kw_index)`）。
新包进仓库即自动获得判别能力——无需每出一个问题就往表里塞一个手写判别词（打地鼠）。

**伞包劫持为何自然消失**：伞包「用户」（用户数据）的目录名就是「用户」二字，
其包罗万象的 **summary 不参与判别**，锚点 keywords 也不来自 summary，故它只在查询
字面含「用户 / 用户数据」时命中；哲学 / 概念类查询（不含「用户」）根本不会落到它头上，无需特判。

## 路由层（resolve_scope 统一入口，返回 (package_id|None, confident:bool)）

别名/缩写/英文全称**一律写在 FM 四要素**（person/topic 变体 dict），由引擎经
`_kw_index`（锚点 keywords 派生）+ `_build_index`（目录名/标题）结构性读取——
新包进仓库自动获得判别力，代码层不保留任何手写别名硬锁表。

两层软信号（均汇入同一 scores 字典取 max，顺序不影响结果）：
  ① 关键词补齐（kw_index，锚点 keywords + FM 四要素变体派生）—— 查询命中某包
     内容词/别名仅加权（+4），**绝不**硬锁。原因：锚点 keyword 含「检索 / 理解 /
     ai」等泛词，命中 demo 包等会触发灾难性误锁。泛词无法承载「锁包」置信度。
  ② 目录名 / 标题结构匹配（_build_index）—— 权重 3/2，易碰撞（如「哲学」），
     同样**绝不**硬锁，交由全库检索 + 伞包降权兜底。

**confident 恒为 False**：两层都是软信号，故 `resolve_scope` 永远返回
`confident=False` → 调用方退全库检索 + 伞包降权兜底，谁都不预先排除，避免错锁
把正确答案所在包直接砍掉。调用方显式传入的 `package_id` / `scope` 仍始终硬过滤
（尊重调用方界定的检索空间）。若要让某包的关键词真正「硬桥接」（如 design-journal
的「双轴框架 / 负载轴」），正确做法是把这些**具体**词写入该包锚点的 `keywords`
字段或 FM 四要素变体（语料层内容补全），而非依赖代码层硬锁——属内容修复，不在路由层。
"""
import io
import os
import re
from typing import Dict, Optional, Set

# ---------------------------------------------------------------------------
# ② 结构路由：扫记忆根，目录名末段 + 包标题 作判别
# ---------------------------------------------------------------------------
_INDEX_CACHE: Dict[str, Dict[str, Set[str]]] = {}


def _tokens(s: str) -> Set[str]:
    """把目录名 / 标题切成判别 token：拉丁词整词、中文 ≥2 字整词（去单字噪点）。"""
    s = (s or "").lower()
    out: Set[str] = set()
    for piece in re.split(r"[^0-9a-z\u4e00-\u9fff]+", s):
        if not piece:
            continue
        if piece.isascii():
            out.add(piece)                       # 拉丁词（aimh / design / journal）
        elif len(piece) >= 2:
            out.add(piece)                       # 中文整词（示例角色 / 存在主义随笔）
    return out


def _first_title(path: str) -> str:
    """轻量读首个 .md 的 front-matter title（不依赖重型解析器）。"""
    try:
        txt = io.open(path, encoding="utf-8").read(4000)
    except Exception:
        return ""
    if not txt.startswith("---"):
        return ""
    m = re.search(r"^title:\s*(.+)$", txt, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def _build_index(memory_root: str,
                 valid_pids: Optional[Set[str]] = None) -> Dict[str, Set[str]]:
    """扫记忆根：对每个含 .md 的包目录，用「目录名末段 + 首 .md 标题」作判别 token。

    valid_pids 限定为 DB 中真实存在的 package_id（避免把未索引的孤立目录
    如「项目/AIMH」也当成可路由包，导致 "aimh" 歧义退全局）。"""
    if memory_root in _INDEX_CACHE:
        return _INDEX_CACHE[memory_root]
    idx: Dict[str, Set[str]] = {}
    root = memory_root.rstrip("/\\")
    for dp, _dn, fn in os.walk(root):
        mds = [f for f in fn if f.endswith(".md")]
        if not mds:
            continue
        rel = os.path.relpath(dp, root).replace("\\", "/")
        if valid_pids is not None and rel not in valid_pids:
            continue
        toks: Set[str] = set(_tokens(rel.split("/")[-1]))     # 目录名末段
        title = _first_title(os.path.join(dp, sorted(mds)[0]))
        if title:
            toks |= _tokens(title)                           # 包标题
        idx[rel] = toks
    _INDEX_CACHE[memory_root] = idx
    return idx


def resolve_scope(q, memory_root: Optional[str] = None,
                  valid_pids: Optional[Set[str]] = None,
                  kw_index: Optional[Dict[str, Set[str]]] = None):
    """查询 → 作用域（包目录 package_id）统一入口，供 query_anchors 缩圈用。

    返回 ``(package_id | None, confident: bool)``：``confident`` 恒为 ``False``
    （两层都是软信号）→ 调用方退全库检索，不硬锁（避免泛词误锁排除正解），
    soft target 仅作排序加权。

    两层（逻辑分层，非执行先后——均汇入同一 scores 字典取 max，顺序不影响结果）：
      ① 关键词补齐（kw_index，各包锚点 keywords 派生，结构性非手写）→ 软加权（+4），
         不触发硬锁（泛词如「检索」会误锁 demo 包）。
      ② 目录名末段（权重 3）/ 标题 token（权重 2）结构匹配 → 仅计分，不单独触发硬锁。
    最终取加权最高包作为软聚焦 target；硬过滤只认调用方显式传入的 package_id / scope。
    """
    ql = str(q).lower()
    if not memory_root:
        return (None, False)
    # ② 目录名 / 标题结构匹配（软信号，权重 3/2）
    idx = _build_index(memory_root, valid_pids)
    scores: Dict[str, float] = {}
    for pid, toks in idx.items():
        tail = pid.rsplit("/", 1)[-1].lower()
        s = 0.0
        for t in toks:
            if t and t in ql:
                s += 3.0 if t in tail else 2.0
        if s:
            scores[pid] = scores.get(pid, 0) + s
    # ① 关键词补齐（锚点 keywords，内容级消歧，权重 4）
    kw_hit = False
    for t, pids in (kw_index or {}).items():
        if t and t in ql:
            kw_hit = True
            for pid in pids:
                scores[pid] = scores.get(pid, 0) + 4.0
    if not scores:
        return (None, False)
    best = max(scores, key=lambda p: scores[p])
    # 两层信号一律 soft-only、绝不硬锁：泛词（检索 / 理解 / ai）命中 demo 等包
    # 会触发灾难性误锁，且错锁会把正确答案所在包直接砍掉。best 仅作软聚焦
    # target；硬过滤只认调用方显式传入的 package_id / scope。
    return (best, False)
