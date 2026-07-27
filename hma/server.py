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


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "hma"
SERVER_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# 工具定义（MCP tools/list 返回）
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "memory_write",
        "description": (
            "写/改一个事件包：原子写 .md（权威源）+ 确定性 upsert 索引。"
            "id 存在则覆盖更新。tags/aliases/linked 为字符串数组。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "事件包唯一 ID（文件名）"},
                "title": {"type": "string", "description": "标题"},
                "summary": {"type": "string", "description": "一句话摘要"},
                "aliases": {"type": "array", "items": {"type": "string"},
                            "description": "别名/同义词，用于检索命中"},
                "tags": {"type": "array", "items": {"type": "string"},
                         "description": "标签；trivial 表示琐碎内容（检索降权）"},
                "linked": {"type": "array", "items": {"type": "string"},
                           "description": "关联的其他事件包 ID"},
                "body": {"type": "string", "description": "Markdown 正文"},
                "created": {"type": "string", "description": "创建日期 YYYY-MM-DD（可选）"},
                "updated": {"type": "string", "description": "更新日期 YYYY-MM-DD（可选）"},
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
            },
            "required": ["q"],
        },
    },
    {
        "name": "memory_query_anchors",
        "description": (
            "锚点层细粒度召回：在事件包的 anchors 子事件锚点上做关键词匹配，"
            "返回命中的子事件（包ID + 锚点标题 + 摘要 + 定位 + 分数）。"
            "用于故事包/长正文按剧情节点召回——当 memory_query 命中率低时，"
            "anchors 往往能把内容词召回（如「幽影核心」「圣保罗之焰」「纽约之战」）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "检索关键词（剧情/事件/特征词）"},
                "top_k": {"type": "integer", "description": "返回条数，默认 5"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "memory_read_section",
        "description": (
            "按小标题精准读取事件包正文的某一段（而非整包），节省上下文窗口。"
            "配合 memory_query_anchors 使用：先 query_anchors 拿到命中的 locator，"
            "再用本工具按 locator 取该段正文。heading 为正文里 ## / ### 小标题的"
            "片段（包含匹配），可直接用 locator 值。"
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
    path = m.write(
        id=a["id"],
        title=a.get("title", "") or a["id"],
        summary=a.get("summary", "") or "",
        aliases=a.get("aliases") or [],
        tags=a.get("tags") or [],
        linked=a.get("linked") or [],
        body=a.get("body", "") or "",
        created=a.get("created"),
        updated=a.get("updated"),
    )
    return f"written: {path}"


def _h_query(root, a):
    m = _store(root)
    hits = m.query(a["q"], top_k=int(a.get("top_k", 5)))
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
    hits = m.query_anchors(a["q"], top_k=int(a.get("top_k", 5)))
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


HANDLERS = {
    "memory_write": _h_write,
    "memory_query": _h_query,
    "memory_query_anchors": _h_query_anchors,
    "memory_read_section": _h_read_section,
    "memory_link": _h_link,
    "memory_rebuild": _h_rebuild,
    "memory_ingest": _h_ingest,
}


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

    sys.stderr.write(f"[hma] MCP server ready, root={root}\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
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
