"""
HMA MCP 服务器（stdio 传输，纯标准库，零第三方依赖）
========================================================

通过 Model Context Protocol 暴露 HMA 记忆工具，可接入任何兼容 MCP 的
AI 客户端（Claude Desktop / Codex / Cline / WorkBuddy / 自建 agent 等）。

协议：stdin/stdout 上的 newline-delimited JSON-RPC 2.0。
仅实现最小可用子集：initialize / tools/list / tools/call。
所有日志走 stderr，stdout 只发协议消息。

启动：
  python -m hma.server --root .memory
  # 或作为 entry point： hma-mcp --root .memory
"""

import sys
import os
import json
import argparse

from .hma_core import Memory
from .ingest import run_ingest
from .llm_adapter import get_adapter
from .envelope import QueryEnvelope, EnvelopeViolation


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "aimh"
SERVER_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# 工具定义（MCP tools/list 返回）
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "memory_write",
        "description": (
            "写/改一个事件包：原子写 .md（权威源）+ 确定性 upsert 索引。"
            "id 为相对 memory/ 的复合路径（不含 .md，如 原创角色/示例角色/demo-base）；"
            "id 存在则覆盖更新。四要素 person/location/topic 为 {规范名:[变体]} 字典"
            "（别名/代号/同义词一律进变体数组，无独立 aliases/features 字段）；anchors 仅"
            "{Chapter,about,keywords}（无 tags/locator）；时间用 pkage_created/pkage_updated，"
            "事件时间用 event_date（YYYY-MM-DD / YYYY-YYYY / '—'）。不传则四要素留空、"
            "anchors 由引擎按 ## 派生。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "事件包复合 ID（相对 memory/ 的路径，不含 .md）；包身份由路径派生"},
                "title": {"type": "string", "description": "标题"},
                "summary": {"type": "string", "description": "2~4句自包含真概要（不写'已废弃/已移除'等元备注）"},
                "tags": {"type": "array", "items": {"type": "string"},
                         "description": "分类标签数组（不放实体名，实体进四要素变体）"},
                "linked": {"type": "array", "items": {"type": "string"},
                           "description": "关联包复合 id（含目录+.md，如 原创角色/示例角色/demo-base.md）"},
                "body": {"type": "string", "description": "Markdown 正文"},
                "pkage_created": {"type": "string", "description": "收录时间 YYYY-MM-DD（可选；不传沿用已有/默认今天）"},
                "pkage_updated": {"type": "string", "description": "更新时间 YYYY-MM-DD（可选；不传默认今天）"},
                "person": {"type": "object",
                           "additionalProperties": {"type": "array", "items": {"type": "string"}},
                           "description": "参与方 {规范全名:[别名/代号/同义词]}；如 {'示例角色':['示例别名','示例代号']}；无变体写 []"},
                "anchors": {"type": "array", "items": {"type": "object", "properties": {
                    "Chapter": {"type": "string", "description": "章节/小节标题（正文定位键，对标 ## 标题）"},
                    "about": {"type": "string", "description": "该节要点梗概（参与锚点匹配、可直答\"这章讲什么\"）"},
                    "keywords": {"type": "array", "items": {"type": "string"},
                                 "description": "章级关键词（满足5维：时间/地点/关键事件/锚定物品/人物 各≥1 token）"},
                }}, "description": "C+A 对象锚点列表 {Chapter,about,keywords}；不传则由引擎按 ## 派生"},
                "event_date": {"type": "string", "description": "事件时间：YYYY-MM-DD / YYYY-YYYY / '—'（无时间信息）"},
                "location": {"type": "object",
                             "additionalProperties": {"type": "array", "items": {"type": "string"}},
                             "description": "地点 {规范名:[变体]}"},
                "topic": {"type": "object",
                          "additionalProperties": {"type": "array", "items": {"type": "string"}},
                          "description": "主题 {规范名:[变体]}（变体里的纯日期=事件发生时间）"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "memory_query",
        "description": (
            "确定性无状态检索：在 id/title/alias/tag/summary 上做关键词匹配，"
            "返回按确定性规则排序的 Top-K 候选（命中唯一 ID）。不依赖热度/权重。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "检索关键词"},
                "top_k": {"type": "integer", "description": "返回条数，默认 5"},
                "multihop": {"type": "boolean",
                             "description": "true=沿 linked 双向 BFS 扩簇多跳召回（跨包关联推理）；默认 false 走单跳关键词匹配"},
                "keywords": {"type": "array", "items": {"type": "string"},
                             "description": "AI 理解层解析出的复合实体词（如 ['量子计算','最新进展']）；传入即启用 corpus_missing_entity 硬拒答闸——判别实体在语料查不到则拒答"},
                "scope": {"type": "string",
                          "description": "聚焦检索：传入目录路径（绝对路径或相对 memory 根），只召回该子树内的记忆、屏蔽其他记忆干扰（如 '项目/AIMH-design-journal' 或绝对路径）。留空=全仓（零回归）。聚焦只收束候选范围，不提升精度、不替你拒答离题问题"},
                "mode": {"type": "string",
                         "description": "查询意图分类（QueryEnvelope 契约，必填）：single=单问 / multi=拆碎多次查询（多跳=其中沿 linked 扩散的手法）/ enumerate=范围枚举。缺省将触发 ENVELOPE_VIOLATION 阻挡"},
                "raw_query": {"type": "string",
                              "description": "可选：原句审计留档（query 装归约后核心句，keywords 从原句抽）。仅记录用，不进引擎"},
                "sub_queries": {"type": "array", "items": {"type": "string"},
                              "description": "multi 模式必填：AI 已拆好的子问题清单（如 ['X 是什么','Y 怎么用']）。引擎确定性扇出合并，不内置拆问。single/enumerate 传空即可"},
            },
            "required": ["q", "keywords", "mode"],
        },
    },
    {
        "name": "memory_query_anchors",
        "description": (
            "锚点层细粒度召回：在事件包的 anchors 子事件锚点上做关键词匹配，"
            "返回命中的子事件（包ID + 锚点标题 + 摘要 + 定位 + 分数）。"
            "用于故事包/长正文按剧情节点召回——当 memory_query 命中率低时，"
            "anchors 往往能把内容词召回（如「示例设定」「示例信物」「纽约之战」）。"
        ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "检索关键词（剧情/事件/特征词）"},
                "top_k": {"type": "integer", "description": "返回条数，默认 5"},
                "allow_abstain": {"type": "boolean", "description": "true=开启拒答层（三道确定性闸门：空池/覆盖不足/四要素越界）；召回不足时返回 (ABSTAIN: reason) 而非硬凑结果。V1.0 起默认 true（拒答层默认开启；传 false 退回旧硬凑行为）"},
                "keywords": {"type": "array", "items": {"type": "string"},
                             "description": "AI 理解层解析出的复合实体词（如 ['量子计算','最新进展']）；传入即启用 corpus_missing_entity 硬拒答闸——判别实体在语料查不到则拒答"},
                "scope": {"type": "string",
                          "description": "聚焦检索：传入目录路径（绝对路径或相对 memory 根），只召回该子树内的记忆、屏蔽其他记忆干扰。留空=全仓（零回归）。聚焦只收束候选范围，不提升精度、不替你拒答离题问题"},
                "mode": {"type": "string",
                         "description": "查询意图分类（QueryEnvelope 契约，必填）：single=单问 / multi=拆碎多次查询（多跳=其中沿 linked 扩散的手法）/ enumerate=范围枚举。缺省将触发 ENVELOPE_VIOLATION 阻挡"},
                "raw_query": {"type": "string",
                              "description": "可选：原句审计留档（query 装归约后核心句，keywords 从原句抽）。仅记录用，不进引擎"},
                "sub_queries": {"type": "array", "items": {"type": "string"},
                              "description": "multi 模式必填：AI 已拆好的子问题清单（如 ['X 是什么','Y 怎么用']）。引擎确定性扇出合并，不内置拆问。single/enumerate 传空即可"},
            },
        "required": ["q", "keywords", "mode"],
        },
    },
    {
        "name": "memory_resolve",
        "description": (
            "召回消歧入口（B 类 resolver）：在确定性关键词召回之上做实体歧义判定——"
            "命中≥2 实体时澄清（亮出各候选独有弧段让用户指认），否则直接返回 Top-K。"
            "multihop=true 时先沿 linked 双向 BFS 扩簇（多跳召回）再跑歧义门；"
            "keywords 可传入 AI 解析出的复合实体词，触发 corpus_missing_entity 硬拒答闸。"
            "这是 linked-BFS + 歧义门机制复用后的生产级统一入口。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "检索关键词"},
                "top_k": {"type": "integer", "description": "返回条数，默认 5"},
                "multihop": {"type": "boolean",
                             "description": "true=沿 linked 多跳扩簇后跑歧义门（跨包关联推理）"},
                "allow_clarify": {"type": "boolean",
                                  "description": "true=多实体时澄清（默认 true）；传 false 直接返回 Top-K"},
                "allow_abstain": {"type": "boolean",
                                  "description": "true=开启拒答层（默认 true）；AI 接口 keywords 传入时，判别实体不在语料则拒答"},
                "keywords": {"type": "array", "items": {"type": "string"},
                             "description": "AI 理解层解析出的复合实体词（如 ['量子计算','最新进展']）；传入即启用 corpus_missing_entity 硬拒答闸"},
                "scope": {"type": "string",
                          "description": "聚焦检索：传入目录路径（绝对路径或相对 memory 根），只召回该子树内的记忆、屏蔽其他记忆干扰。留空=全仓（零回归）。聚焦只收束候选范围，不提升精度、不替你拒答离题问题"},
                "mode": {"type": "string",
                         "description": "查询意图分类（QueryEnvelope 契约，必填）：single=单问 / multi=拆碎多次查询（多跳=其中沿 linked 扩散的手法）/ enumerate=范围枚举。缺省将触发 ENVELOPE_VIOLATION 阻挡"},
                "raw_query": {"type": "string",
                              "description": "可选：原句审计留档（query 装归约后核心句，keywords 从原句抽）。仅记录用，不进引擎"},
                "sub_queries": {"type": "array", "items": {"type": "string"},
                              "description": "multi 模式必填：AI 已拆好的子问题清单（如 ['X 是什么','Y 怎么用']）。引擎确定性扇出合并，不内置拆问。single/enumerate 传空即可"},
            },
            "required": ["q", "keywords", "mode"],
        },
    },
    {
        "name": "memory_read_section",
        "description": (
            "按小标题精准读取事件包正文的某一段（而非整包），节省上下文窗口。"
            "配合 memory_query_anchors 使用：先 query_anchors 拿到命中的锚点 Chapter 标题，"
            "再用本工具按该标题取正文。heading 为正文里 ## / ### 小标题的"
            "片段（包含匹配），可直接用 query_anchors 返回的 loc 值（它即 Chapter 标题，锚点无独立 locator 字段）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "事件包 ID"},
                "heading": {"type": "string", "description": "小标题片段（##/### 标题的包含匹配，可用 query_anchors 返回的 locator）"},
            },
            "required": ["id", "heading"],
        },
    },
    {
        "name": "memory_obscure_recall",
        "description": (
            "不起眼物件 / 长尾细节追问召回（context-scope 章级锁章 + 人机共审）。\n"
            "针对无锚点位、机械层选不出描述段的长尾细节（如『示例角色在伊斯坦布尔那张唱片封面什么样』）：\n"
            "用交互状态提供的章级范围信号绕开机械层无章级定位的死结，章内局部倒排+重叠合并瘦身后走双路线——\n"
            "路线一（范围候选·AI自读理解）：把候选段交AI在窄语境自读；\n"
            "路线二（C+A段卡片·人机共审）：每段以『C章+A锚点about+段原文』卡片摊开，系统不单方出答案、终审权在人。\n"
            "路线一无果→自动拒答并强制降级转路线二。零-ML确定性机械层，precision交理解层或人。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "用户原问句（审计/展示用，不参与机械匹配）"},
                "obj_token": {"type": "string", "description": "特征实体词（章内局部倒排检索词，如『唱片』『钥匙』）"},
                "package_id": {"type": "string", "description": "目标事件包复合 ID（如 原创角色/示例角色/demo-origin）；不传则全仓扫描"},
                "scope_chapter": {"type": "string", "description": "用户显式指明的章标题（强信号直接锁章）；与 scope_mode=explicit 配合"},
                "scope_mode": {"type": "string", "description": "范围信号来源：explicit(强·scope_chapter锁章) / reading(弱·阅读位置缩圈+全包兜底) / global(全包宽召回)；默认 reading"},
                "top_k": {"type": "integer", "description": "返回候选段上限（安全闸），默认 5"},
                "window": {"type": "integer", "description": "局部倒排切窗半径（字符数），默认 200"},
            },
            "required": ["obj_token"],
        },
    },
    {
        "name": "memory_link",
        "description": "双向关联两个事件包（更新两者 front-matter 的 linked 字段）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "事件包 ID"},
                "b": {"type": "string", "description": "事件包 ID"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "memory_rebuild",
        "description": (
            "从所有 .md 的 front-matter 全量重建 index.db。"
            "索引损坏时调用——.md 是权威源，重建不丢数据。"
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "memory_ingest",
        "description": (
            "主动收录：用户提供一段原始文本，AI 执行完整管线——"
            "理解并拆分为凝聚的事件包、生成结构化元数据、写入 .md 权威源 + 索引、"
            "与现有/新建包建立关联。模型由通用适配器决定（模型无关）。"
            "未配置 LLM API 时退化为单包启发式。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待收录的原始文本"},
                "scope": {"type": "string",
                          "description": "作用域标签（如 user_global / workspace_x），会加进每个新包的 tags"},
                "provider": {"type": "string",
                            "description": "可选，覆盖默认 LLM 厂商：openai / anthropic"},
                "model": {"type": "string", "description": "可选，覆盖默认模型名"},
                "auto_link": {"type": "boolean",
                             "description": "是否自动建立关联，默认 true"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "memory_aggregate",
        "description": (
            "计数问（Type 8）的结构化计数器：确定性无 ML 地统计记忆库规模——"
            "unit∈packages(包文件夹数)/events(各包子事件总数)/persons(人物实体去重数)/"
            "locations(地点实体去重数)/topics(主题实体去重数)。结构化入参、绝不透传 raw SQL；"
            "7 道护栏（只读连接 / 列白名单 / 值参数化 / 实体列走 json_each 取规范名 / "
            "行数上限 500 / 显式 scope）。filters 为 {列:值} 精确匹配（列限白名单，非法列被拒）；"
            "event_date_like 为事件日期前缀模糊（如 '2026-03'）；scope 收束到某子树；"
            "return_list=true 返回实体枚举列表而非计数。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "unit": {"type": "string",
                         "description": "计数单位：packages / events / persons / locations / topics"},
                "filters": {"type": "object",
                             "additionalProperties": {"type": "string"},
                             "description": "精确过滤：{列:值}，列限白名单(package_id/filepath/title/summary/tags/linked/pkage_created/pkage_updated/anchors/person/event_date/location/topic)；如 {'tags':'项目进度'}。非法列触发 ValueError 被拒"},
                "event_date_like": {"type": "string",
                                     "description": "事件日期前缀模糊（便利封装，等价于 filters={'event_date':('like',值)}）；如 '2026-03' 统计 2026 年 3 月的记忆"},
                "scope": {"type": "string",
                          "description": "聚焦计数：传入目录路径（绝对或相对 memory 根），只统计该子树；留空=全仓"},
                "return_list": {"type": "boolean",
                                "description": "true=返回实体枚举列表（packages→包ID；persons/locations/topics→规范名；events→'包ID::章节'），而非计数。默认 false"},
                "top_k": {"type": "integer",
                          "description": "return_list 模式的返回上限，硬上限 500，默认 500"},
            },
            "required": ["unit"],
        },
    },
    {
        "name": "memory_time_filter",
        "description": (
            "时间硬过滤（Type 6）：解析自然语言时间意图，硬留 event_date 命中"
            "月（含年）的记忆包。零 ML、确定性、只读连接；复用生产 parse_time_hint"
            "做时间意图抽取（支持 ISO / 英文月名 / 中文「2026年3月」「三月」/ 相对时间"
            "如『90 days ago』），对每包 event_date 做确定性月份硬匹配——不匹配月即剔除"
            "（与 query_anchors 的软时间加权只偏不强制相对）。time_hint 无时间意图→返回空；"
            "年范围事件日期（如『1792-1822』）无月份信号→被剔除（与软加权语义一致）。"
            "scope 收束到某子树（memory 根下的完整相对路径，如『其他/对话记录归档』）；"
            "留空=全仓。返回命中包的 package_id 列表。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "time_hint": {"type": "string",
                              "description": "自然语言时间意图，如 '2026年3月' / '三月' / '2026年' / '90 days ago'"},
                "scope": {"type": "string",
                          "description": "聚焦子树：memory 根下的完整相对路径（如 '其他/对话记录归档'）；留空=全仓"},
                "top_k": {"type": "integer",
                          "description": "返回包数上限，硬上限 500，默认 500"},
            },
            "required": ["time_hint"],
        },
    },
]


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------

def _store(root):
    """复用同一 root 的 Memory 实例（同一 SQLite 连接）。

    MCP server 是单进程单线程长驻；若每次 tools/call 都 Memory(root) 新建
    实例却从不 close()，会泄漏 SQLite 连接与文件锁。按 root 缓存单例即可
    （单 root 场景下缓存仅一条目）。"""
    m = _MEM_CACHE.get(root)
    if m is None:
        m = Memory(root)
        _MEM_CACHE[root] = m
    return m


_MEM_CACHE = {}


def _h_write(root, a):
    m = _store(root)
    # V2：id 即相对 memory/ 的复合路径（不含 .md）；时间用 pkage_* 映射到引擎
    # created/updated；四要素 dict / anchors {Chapter,about,keywords} 由 AI 直接给，
    # 不再经 aliases/features 旧字段（避免别名被误折成规范名）。
    # 兜底（R-safety）：body 缺省/为空时，自动读取现有正文回填，避免清空既有正文
    # （历史上 memory_write 漏传 body 导致设计期刊两篇文档正文被清空）。仅当现有
    # 文件确有非空正文才回填；新建（无现有文件）仍允许空 body。Memory.write 的
    # force_empty_body 护栏作为第二道防线（MCP 不暴露该开关，故经 MCP 永远无法清空正文）。
    body = a.get("body")
    if not body:
        existing = m.read_body(a["id"])
        if existing:
            body = existing
    body = body or ""
    path = m.write(
        id=a["id"],
        title=a.get("title", "") or a["id"],
        summary=a.get("summary", "") or "",
        tags=a.get("tags") or [],
        linked=a.get("linked") or [],
        body=body,
        anchors=a.get("anchors"),
        person=a.get("person"),
        location=a.get("location"),
        topic=a.get("topic"),
        event_date=a.get("event_date"),
        pkage_created=a.get("pkage_created"),
        pkage_updated=a.get("pkage_updated"),
    )
    return f"written: {path}"


def _fmt_orchestrate(out):
    """格式化 Memory.orchestrate 的 [(sub_q, hits, reason), ...] 返回。"""
    blocks = []
    any_hit = False
    for sq, hits, reason in out:
        head = f"### 子问: {sq}"
        if reason:
            blocks.append(f"{head}\n    (ABSTAIN: {reason}) 子问无匹配，请勿编造")
            continue
        if not hits:
            blocks.append(f"{head}\n    (no anchor match)")
            continue
        any_hit = True
        lines = [head]
        for pkg_id, a_title, a_summary, locator, score in hits:
            lines.append(f"  [{score:>3}] {pkg_id} :: {a_title}")
            if a_summary:
                lines.append(f"          {a_summary}")
            if locator:
                lines.append(f"          loc: {locator}")
        blocks.append("\n".join(lines))
    if not any_hit:
        return "(no anchor match across sub-queries)"
    return "\n\n".join(blocks)


def _h_query(root, a):
    m = _store(root)
    try:
        env = QueryEnvelope(
            query=a.get("q", ""),
            keywords=a.get("keywords") or [],
            mode=a.get("mode", ""),
            scope=a.get("scope"),
            allow_abstain=bool(a.get("allow_abstain", True)),
            multihop=bool(a.get("multihop", False)),
            raw_query=a.get("raw_query"),
            sub_queries=a.get("sub_queries") or [],
            top_k=int(a.get("top_k", 5)),
        )
    except EnvelopeViolation as e:
        return (f"(ENVELOPE_VIOLATION: {e}) 请按 QueryEnvelope 契约传参："
                f"q+keywords+mode 必填，mode∈single|multi|enumerate")
    if env.mode == "enumerate":
        items = m.list_all_in_scope(scope=env.scope, top_k=env.top_k)
        if not items:
            return "(no package in scope)"
        return "\n".join(
            f"{rid}  —  {title}" + (f"\n        {summary}" if summary else "")
            for rid, title, summary in items)
    if env.mode == "multi":
        out = m.orchestrate(env.sub_queries, top_k=env.top_k,
                            keywords=env.keywords, scope=env.scope,
                            allow_abstain=env.allow_abstain)
        return _fmt_orchestrate(out)
    if env.multihop:
        hits = m.recall_multihop(env.query, top_k=env.top_k, keywords=env.keywords)
    else:
        hits = m.query(env.query, top_k=env.top_k,
                       keywords=env.keywords, scope=env.scope)
    if not hits:
        return "(no match)"
    lines = []
    for rid, title, summary, score in hits:
        lines.append(f"[{score:>3}] {rid}  —  {title}")
        if summary:
            lines.append(f"        {summary}")
    return "\n".join(lines)


def _h_query_anchors(root, a):
    m = _store(root)
    try:
        env = QueryEnvelope(
            query=a.get("q", ""),
            keywords=a.get("keywords") or [],
            mode=a.get("mode", ""),
            scope=a.get("scope"),
            allow_abstain=bool(a.get("allow_abstain", True)),
            raw_query=a.get("raw_query"),
            sub_queries=a.get("sub_queries") or [],
            top_k=int(a.get("top_k", 5)),
        )
    except EnvelopeViolation as e:
        return (f"(ENVELOPE_VIOLATION: {e}) 请按 QueryEnvelope 契约传参："
                f"q+keywords+mode 必填，mode∈single|multi|enumerate")
    if env.mode == "enumerate":
        items = m.list_all_in_scope(scope=env.scope, top_k=env.top_k)
        if not items:
            return "(no package in scope)"
        return "\n".join(
            f"{rid}  —  {title}" + (f"\n        {summary}" if summary else "")
            for rid, title, summary in items)
    if env.mode == "multi":
        out = m.orchestrate(env.sub_queries, top_k=env.top_k,
                            keywords=env.keywords, scope=env.scope,
                            allow_abstain=env.allow_abstain)
        return _fmt_orchestrate(out)
    hits = m.query_anchors(env.query, top_k=env.top_k,
                           allow_abstain=env.allow_abstain, use_field_weights=True,
                           keywords=env.keywords, scope=env.scope)
    if isinstance(hits, dict):                 # allow_abstain=True 的结构化返回
        if hits["abstain"]:
            return f"(ABSTAIN: {hits['reason']}) 记忆中无匹配，请勿编造"
        hits = hits["answer"]
    if not hits:
        return "(no anchor match)"
    lines = []
    for pkg_id, a_title, a_summary, locator, score in hits:
        lines.append(f"[{score:>3}] {pkg_id} :: {a_title}")
        if a_summary:
            lines.append(f"        {a_summary}")
        if locator:
            lines.append(f"        loc: {locator}")
    return "\n".join(lines)


def _h_resolve(root, a):
    """召回消歧入口（B 类 resolver）：确定性召回之上做实体歧义判定 + 多跳扩簇。

    把 `resolve_query` 接到真实读取链路：multihop=true 时先沿 linked 双向 BFS
    扩簇（多跳召回）再跑实体歧义门；keywords 传入 AI 解析出的复合实体，启用
    corpus_missing_entity 硬拒答闸。这是 linked-BFS + 歧义门机制复用后的生产级
    统一入口（此前 agent 只能走裸 recall_multihop，绕过歧义门）。
    """
    m = _store(root)
    try:
        env = QueryEnvelope(
            query=a.get("q", ""),
            keywords=a.get("keywords") or [],
            mode=a.get("mode", ""),
            scope=a.get("scope"),
            allow_abstain=bool(a.get("allow_abstain", True)),
            multihop=bool(a.get("multihop", False)),
            raw_query=a.get("raw_query"),
            sub_queries=a.get("sub_queries") or [],
            top_k=int(a.get("top_k", 5)),
        )
    except EnvelopeViolation as e:
        return (f"(ENVELOPE_VIOLATION: {e}) 请按 QueryEnvelope 契约传参："
                f"q+keywords+mode 必填，mode∈single|multi|enumerate")
    if env.mode == "enumerate":
        items = m.list_all_in_scope(scope=env.scope, top_k=env.top_k)
        if not items:
            return "(no package in scope)"
        return "\n".join(
            f"{rid}  —  {title}" + (f"\n        {summary}" if summary else "")
            for rid, title, summary in items)
    if env.mode == "multi":
        out = m.orchestrate(env.sub_queries, top_k=env.top_k,
                            keywords=env.keywords, scope=env.scope,
                            allow_abstain=env.allow_abstain)
        return _fmt_orchestrate(out)
    res = m.resolve_query(
        env.query, top_k=env.top_k,
        multihop=env.multihop,
        allow_clarify=bool(a.get("allow_clarify", True)),
        allow_abstain=env.allow_abstain,
        keywords=env.keywords,
        scope=env.scope,
    )
    if res["decision"] == "abstain":
        return f"(ABSTAIN: {res['reason']}) 记忆中无匹配，请勿编造"
    if res["decision"] == "clarify":
        # 命中多个候选实体：把每候选的「简介 + 判别特征」拼成紧凑文本，作为
        # MCP 工具结果回给【调用方 AI】，由 AI 再润色成自然语言向用户澄清。
        # 不可把原始 resolve_query 结构模板直接丢给用户——那是引擎↔AI 契约。
        cands = res["payload"]["candidates"]
        lines = ["[CLARIFY] 命中多个候选实体，请据下列特征向用户澄清具体指哪一个："]
        for i, c in enumerate(cands, 1):
            summary = c.get("summary") or ""
            arc = ", ".join(c.get("unique", [])[:6])
            lines.append(f"  {i}. {c['title']}  (rid={c['rid']})")
            if summary:
                lines.append(f"     简介: {summary}")
            if arc:
                lines.append(f"     判别特征: [{arc}]")
        return "\n".join(lines)
    results = res.get("results", [])
    if not results:
        return "(no match)"
    lines = []
    for rid, title, summary, score in results:
        lines.append(f"[{score:>3}] {rid}  —  {title}")
        if summary:
            lines.append(f"        {summary}")
    return "\n".join(lines)


def _h_read_section(root, a):
    m = _store(root)
    section = m.read_section(a["id"], a["heading"])
    if section is None:
        return f"(section not found: {a['heading']!r} in {a['id']})"
    return section


def _h_link(root, a):
    m = _store(root)
    m.link(a["a"], a["b"])
    return f"linked: {a['a']} <-> {a['b']}"


def _h_rebuild(root, a):
    m = _store(root)
    n = m.rebuild()
    return f"rebuilt index: {n} event packages"


def _h_ingest(root, a):
    m = _store(root)
    provider = a.get("provider") or os.environ.get("HMA_LLM")
    model = a.get("model")
    adapter = None
    if provider or model or os.environ.get("OPENAI_API_KEY") \
            or os.environ.get("ANTHROPIC_API_KEY"):
        try:
            adapter = get_adapter(provider=provider, model=model)
        except Exception:
            adapter = None
    auto_link = a.get("auto_link", True)
    if isinstance(auto_link, str):
        auto_link = auto_link.lower() not in ("false", "0", "no")
    return run_ingest(
        m, a.get("text", ""), adapter=adapter,
        scope=a.get("scope"), auto_link=auto_link,
    )


def _h_aggregate(root, a):
    """计数问（Type 8）：结构化计数器，转发到 Memory.aggregate（db_aggregate 后端）。

    零 ML、确定性；结构化入参，绝不接收/透传 raw SQL。event_date_like 便捷封装
    成 filters={'event_date':('like',值)}。非法列/算子由引擎 ValueError 拦截，
    经 MCP 以 isError 文本回包（不让连接断）。"""
    m = _store(root)
    unit = a.get("unit", "")
    if unit not in ("packages", "events", "persons", "locations", "topics"):
        return f"(BAD_UNIT: {unit!r}) unit 必须是 packages/events/persons/locations/topics 之一"
    filters = dict(a.get("filters") or {})
    # event_date_like 便捷封装：等价于 filters['event_date']=('like',值)
    # 语义为「事件日期前缀模糊」，故自动补 % 通配（如 '2026-03' -> '2026-03%'）
    dlike = a.get("event_date_like")
    if dlike:
        if not dlike.endswith("%"):
            dlike = dlike + "%"
        filters["event_date"] = ("like", dlike)
    return_list = bool(a.get("return_list", False))
    top_k = int(a.get("top_k", 500))
    try:
        res = m.aggregate(unit, filters=filters or None,
                          scope=a.get("scope"), return_list=return_list, top_k=top_k)
    except ValueError as e:
        return f"(AGG_GUARD: {e}) 计数被护栏拒绝"
    if return_list:
        if not res:
            return "(no match)"
        return "\n".join(f"- {x}" for x in res)
    return f"count({unit})" + (f" [scope={a['scope']}]" if a.get("scope") else "") + f" = {res}"


def _h_time_filter(root, a):
    """时间硬过滤（Type 6）：转发到 Memory.filter_by_time（time_filter 后端）。

    零 ML、确定性；结构化入参，绝不透传 raw SQL；复用生产 parse_time_hint。
    time_hint 解析不到时间意图→返回空（与引擎一致）。异常经 MCP 以 isError 文本
    回包（不让连接断）。"""
    m = _store(root)
    time_hint = a.get("time_hint", "")
    if not time_hint:
        return "(no time hint)"
    try:
        res = m.filter_by_time(time_hint, scope=a.get("scope"), top_k=int(a.get("top_k", 500)))
    except Exception as e:
        return f"(TIME_FILTER_GUARD: {e}) 时间过滤被拒"
    if not res:
        return "(no match)"
    return "\n".join(f"- {x}" for x in res)


def _h_obscure_recall(root, a):
    """不起眼物件 / 长尾细节追问召回入口。

    转发到 Memory.obscure_recall（context-scope 章级锁章 + 双路线人机共审）。
    返回结构化 dict 的 JSON 文本（与 query_anchors 的 allow_abstain 返回风格对齐），
    供 AI 理解层按 route 字段决定：路线一直接消费候选段自读，或路线二把 C+A 卡片摊给用户。
    """
    m = _store(root)
    try:
        res = m.obscure_recall(
            q=a.get("q", ""),
            obj_token=a.get("obj_token", ""),
            package_id=a.get("package_id") or None,
            scope_chapter=a.get("scope_chapter") or None,
            scope_mode=a.get("scope_mode", "reading"),
            top_k=int(a.get("top_k", 5)),
            window=int(a.get("window", 200)),
        )
    except Exception as e:
        return f"(OBSCURE_GUARD: {e}) 细节召回被拒"
    import json as _json
    return _json.dumps(res, ensure_ascii=False, indent=2)


HANDLERS = {
    "memory_write": _h_write,
    "memory_query": _h_query,
    "memory_query_anchors": _h_query_anchors,
    "memory_resolve": _h_resolve,
    "memory_read_section": _h_read_section,
    "memory_link": _h_link,
    "memory_rebuild": _h_rebuild,
    "memory_ingest": _h_ingest,
    "memory_aggregate": _h_aggregate,
    "memory_time_filter": _h_time_filter,
    "memory_obscure_recall": _h_obscure_recall,
}


# ---------------------------------------------------------------------------
# 入站参数编码兜底
# ---------------------------------------------------------------------------
def _fix_str(s):
    """修复 MCP 客户端传输中文参数时的编码损坏（Windows locale/cp936 等）。

    正常中文不含 surrogate 也无法 latin-1 编码，故对正常字符串零副作用；
    仅对损坏字符串尝试还原，失败则原样返回。"""
    if not isinstance(s, str):
        return s
    # 策略A: 含 surrogate(\\udcXX) -> surrogateescape 还原成原始字节再 UTF-8 解码
    if any('\udc00' <= c <= '\udcff' for c in s):
        try:
            return s.encode('utf-8', 'surrogateescape').decode('utf-8')
        except Exception:
            pass
    # 策略B: UTF-8 字节被当 latin-1 解码 (如 'ç¬¬ä¸‰')
    try:
        return s.encode('latin-1').decode('utf-8')
    except Exception:
        pass
    return s


def _fix_args(a):
    """递归修复 arguments 里所有字符串值。"""
    if isinstance(a, dict):
        return {k: _fix_args(v) for k, v in a.items()}
    if isinstance(a, list):
        return [_fix_args(v) for v in a]
    return _fix_str(a)


# ---------------------------------------------------------------------------
# JSON-RPC 调度（最小子集）
# ---------------------------------------------------------------------------

def _ok(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def dispatch(req, root):
    method = req.get("method")
    req_id = req.get("id")

    # 通知（无 id）：不回包
    if method == "notifications/initialized":
        return None
    if method == "initialized":
        return None

    if method == "ping":
        return _ok(req_id, {})

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "tools/list":
        return _ok(req_id, {"tools": TOOLS})

    if method == "tools/call":
        name = req.get("params", {}).get("name")
        args = req.get("params", {}).get("arguments", {}) or {}
        args = _fix_args(args)   # 兜底：修复客户端传输中文时的编码损坏
        fn = HANDLERS.get(name)
        if not fn:
            return _err(req_id, -32601, f"unknown tool: {name}")
        try:
            text = fn(root, args)
            return _ok(req_id, {"content": [{"type": "text", "text": text}],
                               "isError": False})
        except Exception as e:  # 工具内部错误 -> isError，不让连接断
            return _ok(req_id, {
                "content": [{"type": "text", "text": f"ERROR: {e}"}],
                "isError": True,
            })

    return _err(req_id, -32601, f"method not found: {method}")


def main():
    ap = argparse.ArgumentParser(prog="hma-mcp", description="HMA MCP server (stdio)")
    ap.add_argument("--root", default=os.environ.get("HMA_ROOT", "memory"), help="记忆库根目录（含子包/事件 .md）；默认 memory/ 仓库根，repo 级全局检索")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    os.makedirs(root, exist_ok=True)  # R50：包目录即事件容器（移除 events/）

    sys.stderr.write(f"[aimh] MCP server ready, root={root}\n")
    sys.stderr.flush()

    # 强制 UTF-8 IO：Windows 默认 locale 编码(cp936) 会把客户端发来的
    # UTF-8 JSON-RPC 中文参数解码成乱码，造成 read_section/query_anchors
    # 的中文 heading/q 损坏。此处直接从原始字节按 UTF-8 解码，规避 locale。
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    _in_buf = getattr(sys.stdin, "buffer", None)

    def _lines():
        if _in_buf is not None:
            for raw in _in_buf:
                yield raw.decode("utf-8", errors="replace").strip()
        else:
            for ln in sys.stdin:
                yield ln.strip()

    for line in _lines():
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"[hma] bad json: {e}\n")
            sys.stderr.flush()
            continue
        try:
            resp = dispatch(req, root)
        except Exception as e:
            sys.stderr.write(f"[hma] dispatch error: {e}\n")
            sys.stderr.flush()
            resp = _err(req.get("id"), -32603, f"internal error: {e}")
        if resp is None:
            continue
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
