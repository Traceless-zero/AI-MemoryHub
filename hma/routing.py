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

## 三层（resolve_scope 统一入口，返回 (package_id|None, confident:bool)）

  ① SUBJECT_SCOPE —— 仅收录「无法从目录名 / 标题结构推导」的真别名
     （子实体 / 英文全称，如 圣保罗之焰 / veronica / hybrid memory architecture）。
     **唯一** `confident=True` 来源 → 调用方应**硬锁**候选池到该包。
  ② 关键词补齐（kw_index，锚点 keywords 派生）—— 软信号：查询命中某包 Specific
     内容词仅加权（+4），**绝不**硬锁。原因：锚点 keyword 含「检索 / 理解 / ai」等
     泛词，命中 demo 包等会触发灾难性误锁（T08 曾因此锁到 `样式demo/demo-Project`）。
     泛词无法承载「锁包」置信度，故关键词补齐只做软聚焦，硬锁权完全交给别名层。
  ③ 目录名 / 标题结构匹配（_build_index）—— 软信号（权重 3/2），易碰撞（如「哲学」），
     同样**绝不**硬锁，交由全库检索 + 伞包降权兜底。

**hard 锁 vs 全库的分界（confident 标志）**：**只有①别名**才 `confident=True` 硬锁
候选池；②③ 仅计分/软聚焦，`confident=False` → 退全库，谁都不预先排除，避免错锁把
正确答案所在包直接砍掉（旧实现 T08/T12 误锁「哲学」包、T08 误锁 demo 包皆此因）。
若要让某包的关键词真正「硬桥接」（如 design-journal 的「双轴框架 / 负载轴」），
正确做法是把这些**具体**词写入该包锚点的 `keywords` 字段（语料层内容补全），而非
依赖泛词硬锁——属内容修复，不在路由层。
"""
import io
import os
import re
from typing import Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# ① 非结构性可推导的真别名（极小集合）
# ---------------------------------------------------------------------------
# 只放「目录名 / 标题结构推导不出」的别名：子实体（圣保罗之焰 / 幽影核心 /
# 阴影权能，不在任何目录名里）、英文全称（veronica / hybrid memory architecture /
# cognitive event-driven）。维罗妮卡 / aimh / 哲学 等已由目录名结构性覆盖，不在此列。
# 值 = 包目录 package_id（与 events.package_id 同格式）。
SUBJECT_SCOPE = {
    # design-journal 判别别名（HMA / CEMA 是项目别名；hybrid memory architecture /
    # cognitive event-driven 是 HMA / CEMA 的英文全称别名，目录名里没有）。
    "hma": "项目/AIMH-design-journal",
    "cema": "项目/AIMH-design-journal",
    "hybrid memory architecture": "项目/AIMH-design-journal",
    "cognitive event-driven": "项目/AIMH-design-journal",
    # 维罗妮卡子实体 / 英文别名：全局 query_anchors 历史上会被伞包「用户数据」截胡，
    # 这里精准归到其归属包（目录名「维罗妮卡·夏·雪莱」也能结构性命中，此处双保险）。
    "维罗妮卡": "原创角色/维罗妮卡·夏·雪莱",
    "veronica": "原创角色/维罗妮卡·夏·雪莱",
    "圣保罗之焰": "原创角色/维罗妮卡·夏·雪莱",
    "幽影核心": "原创角色/维罗妮卡·夏·雪莱",
    "阴影权能": "原创角色/维罗妮卡·夏·雪莱",
}

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
            out.add(piece)                       # 中文整词（维罗妮卡 / 存在主义随笔）
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

    返回 ``(package_id | None, confident: bool)``：
      - ``confident=True``（仅① 别名命中）→ 调用方应**硬锁**候选池到该包；
      - ``confident=False``（② 关键词补齐 / ③ 目录名·标题弱匹配）→ 退全库检索
        （不硬锁，避免泛词误锁排除正解；软信号仅作排序加权）。

    三层（顺序固定）：
      ① SUBJECT_SCOPE 别名（强置信）→ 直接返回。
      ② 关键词补齐（kw_index，各包锚点 keywords 派生，结构性非手写）→ 软加权（+4），
         不触发硬锁（泛词如「检索」会误锁 demo 包）。
      ③ 目录名末段（权重 3）/ 标题 token（权重 2）结构匹配 → 仅计分，不单独触发硬锁。
    最终取加权最高包；但 ``confident`` 恒为「是否命中别名」——②③ 一律 False。
    """
    ql = str(q).lower()
    # ① 别名（强置信）
    for alias, pkg in SUBJECT_SCOPE.items():
        if alias in ql:
            return (pkg, True)
    if not memory_root:
        return (None, False)
    # ③ 目录名 / 标题结构匹配（弱置信计分）
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
    # ② 关键词补齐（锚点 keywords，内容级消歧，权重 4）
    kw_hit = False
    for t, pids in (kw_index or {}).items():
        if t and t in ql:
            kw_hit = True
            for pid in pids:
                scores[pid] = scores.get(pid, 0) + 4.0
    if not scores:
        return (None, False)
    best = max(scores, key=lambda p: scores[p])
    # 强置信（confident）恒为「是否命中①别名」——②③ 的关键词补齐 / 目录名匹配
    # 一律 soft-only、绝不硬锁：泛词（检索 / 理解 / ai）命中 demo 等包会触发灾难性
    # 误锁（T08 曾锁到 样式demo/demo-Project）。硬锁权完全交给别名层；其余退全库 +
    # 伞包降权兜底。best 仍作为软聚焦 target 候选，但调用方仅在 confident 时硬用。
    return (best, False)
