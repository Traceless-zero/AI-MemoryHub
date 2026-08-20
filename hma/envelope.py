"""QueryEnvelope — AI→引擎 查询调用的强制契约（零-ML 确定性校验层）。

让 AI 每次查询都先构造统一信封，杜绝漏传 keywords（corpus_missing_entity 硬拒答闸的
唯一输入）。本层只做校验/归一，不碰引擎检索逻辑；引擎原语不变（CEMA：理解前置到写/查侧）。

契约字段：
  mode      ∈ {single, multi, enumerate}   必填，用户意图分类（非引擎路径）
  query     str                            必填非空；长难句须先归约成核心句再传入
  keywords  list[str]                      必填非空；从【原句】抽的实体/上下文词，驱动硬拒答闸
  scope     str|None                       可选；枚举/聚焦用（相对 memory 根或绝对路径）
  allow_abstain bool                      默认 True
  multihop  bool                          默认 False；multi 模式下的 linked 扩散手法时置 True
  raw_query str|None                      可选；原句审计留档（与 query 的归约后核心句区分）
  sub_queries list[str]|None              multi 模式必填；AI 已拆好的子问题清单，引擎确定性扇出（不内置拆问）
  top_k     int                           默认 5

设计约定（与用户敲定）：
  - 多问题本质=拆碎多次查询，A+B 与 A→A`（沿 linked 派生）底层相同 → 多跳不是独立 mode，
    只是 multi 下的一种分解手法，靠 multihop 旗标表达。
  - 长难句（汉佛莱式）不是独立模式，是"归约前置 + keywords 从原句抽"的质量门槛：
    query 装归约后核心句，keywords 从原句抽。
  - 全局搜索=关键词相关度；多跳=沿写入时策展的 linked 边 BFS 扩簇，补"关系/结构"盲区，opt-in。
"""
from dataclasses import dataclass
from typing import List, Optional

VALID_MODES = ("single", "multi", "enumerate")


class EnvelopeViolation(ValueError):
    """调用方未遵守 QueryEnvelope 契约。MCP 边界捕获后直接阻挡，不进引擎。"""


@dataclass
class QueryEnvelope:
    query: str
    keywords: List[str]
    mode: str = "single"
    scope: Optional[str] = None
    allow_abstain: bool = True
    multihop: bool = False
    raw_query: Optional[str] = None
    sub_queries: Optional[List[str]] = None
    top_k: int = 5

    def __post_init__(self):
        self.validate()

    def validate(self) -> "QueryEnvelope":
        q = (self.query or "").strip()
        if not q:
            raise EnvelopeViolation(
                "q 必填且非空：长难句须先归约成核心句（多问题拆碎、汉佛莱式先榨干）再传入")
        if self.mode not in VALID_MODES:
            raise EnvelopeViolation(
                f"mode 必须是 {VALID_MODES} 之一，收到: {self.mode!r}。"
                "single=单问 / multi=拆碎多次查询(多跳=其中沿 linked 扩散的手法) / enumerate=范围枚举")
        ks = [str(k).strip() for k in (self.keywords or []) if str(k).strip()]
        if not ks:
            raise EnvelopeViolation(
                "keywords 必填且非空：它是 corpus_missing_entity 硬拒答闸的唯一输入，"
                "从【原句】抽取实体/上下文词；漏传会退化成弱闸、复合实体无法硬拒")
        if self.mode == "enumerate" and not (self.scope and str(self.scope).strip()):
            raise EnvelopeViolation(
                "enumerate 模式必须带 scope：它列出该子树内的全部包，无 scope 即无枚举对象"
                "（如 scope='项目/AIMH-design-journal' 或绝对路径）")
        if self.mode == "multi":
            sq = [str(s).strip() for s in (self.sub_queries or []) if str(s).strip()]
            if not sq:
                raise EnvelopeViolation(
                    "multi 模式必须带 sub_queries：AI 先拆好子问题清单（如 ['X 是什么','Y 怎么用']），"
                    "引擎确定性扇出合并；不内置拆问（拆问归 AI 理解层，CEMA）")
            self.sub_queries = sq
        self.query = q
        self.keywords = ks
        if self.scope is not None and not str(self.scope).strip():
            self.scope = None
        self.top_k = int(self.top_k if self.top_k is not None else 5)
        return self

    def engine_kwargs(self) -> dict:
        """映射到 query / query_anchors 通用入参。"""
        return dict(q=self.query, keywords=self.keywords,
                   scope=self.scope, allow_abstain=self.allow_abstain)

    def resolve_kwargs(self) -> dict:
        """映射到 resolve_query 入参（额外带 multihop）。"""
        return dict(**self.engine_kwargs(), multihop=self.multihop)
