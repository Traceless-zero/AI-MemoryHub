"""
HMA 通用大模型 API 适配器（零第三方依赖，仅标准库 urllib）
============================================================

目标：让 HMA 能对接**任意** AI 大模型 API。HMA 本身不绑定任何模型——
它只暴露工具；真正"决定是否记忆、调用哪个工具"的是 LLM。这个适配器
把不同厂商的 API 差异收敛成一个统一接口，于是你可以今天用 Claude、
明天换 GPT、后天换本地 Ollama / DeepSeek / Qwen，代码一行不改。

已内置两类适配器：
  - OpenAICompatibleAdapter：OpenAI、Groq、Together、DeepSeek、
    Moonshot、Ollama(openai 兼容模式)、vLLM、LM Studio……（凡 OpenAI
    /chat/completions 兼容的都行）
  - AnthropicAdapter：Anthropic Claude 官方 API

通过环境变量配置，无需改代码：
  OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL
  ANTHROPIC_API_KEY / ANTHROPIC_MODEL

用法见 examples/basic_agent.py。
"""

import os
import json
import urllib.request
import urllib.error


# HMA 工具以 OpenAI tools 格式声明（两种适配器都围绕它转换）
HMA_TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": (
                "写/改一个事件包：原子写 .md（权威源）+ 确定性 upsert 索引。"
                "id 为相对 memory/ 的复合路径（不含 .md）；id 存在则覆盖更新。"
                "四要素 person/location/topic 为 {规范名:[变体]} 字典（别名/代号进变体数组，"
                "无独立 aliases/features）；anchors 仅 {Chapter,about,keywords}；时间用 "
                "pkage_created/pkage_updated，事件时间用 event_date。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "事件包复合 ID（相对 memory/ 的路径，不含 .md）；包身份由路径派生"},
                    "title": {"type": "string", "description": "标题"},
                    "summary": {"type": "string", "description": "2~4句自包含真概要（不写'已废弃/已移除'等元备注）"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "分类标签数组（不放实体名）"},
                    "linked": {"type": "array", "items": {"type": "string"}, "description": "关联包复合 id（含目录+.md）"},
                    "body": {"type": "string", "description": "Markdown 正文"},
                    "pkage_created": {"type": "string", "description": "收录时间 YYYY-MM-DD（可选；不传默认今天）"},
                    "pkage_updated": {"type": "string", "description": "更新时间 YYYY-MM-DD（可选；不传默认今天）"},
                    "person": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}, "description": "参与方 {规范全名:[别名/代号/同义词]}；如 {'维罗妮卡·夏·雪莱':['午夜魅影','PR-7']}"},
                    "anchors": {"type": "array", "items": {"type": "object", "properties": {
                        "Chapter": {"type": "string", "description": "章节/小节标题（正文定位键，对标 ## 标题）"},
                        "about": {"type": "string", "description": "该节要点梗概（参与锚点匹配、可直答\"这章讲什么\"）"},
                        "keywords": {"type": "array", "items": {"type": "string"}, "description": "章级关键词（5维：时间/地点/关键事件/锚定物品/人物 各≥1）"},
                    }}, "description": "C+A 对象锚点列表 {Chapter,about,keywords}；不传则由引擎按 ## 派生"},
                    "event_date": {"type": "string", "description": "事件时间：YYYY-MM-DD / YYYY-YYYY / '—'（无时间信息）"},
                    "location": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}, "description": "地点 {规范名:[变体]}"},
                    "topic": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}, "description": "主题 {规范名:[变体]}（变体里纯日期=事件发生时间）"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_query",
            "description": "确定性检索记忆，返回 Top-K 候选。",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "top_k": {"type": "integer"},
                    "keywords": {
                        "type": "array", "items": {"type": "string"},
                        "description": "AI 理解层解析出的复合实体词（如 ['量子计算','最新进展']）；传入即启用 corpus_missing_entity 硬拒答闸",
                    },
                },
                "required": ["q"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_link",
            "description": "双向关联两个事件包。",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "string"},
                    "b": {"type": "string"},
                },
                "required": ["a", "b"],
            },
        },
    },
]


def _http_post(url, headers, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"network error: {e.reason}")


class LLMAdapter:
    """统一接口。子类实现 chat() 与 parse_tool_calls()。"""

    def chat(self, messages, tools=None, tool_choice="auto"):
        raise NotImplementedError

    def parse_tool_calls(self, response):
        raise NotImplementedError

    def content_text(self, response):
        raise NotImplementedError

    def assistant_with_tools(self, content, calls):
        """把 (文本 + 工具调用) 组装成当前厂商格式的 assistant 消息。
        返回 (message_dict, [tool_call_id, ...])。"""
        raise NotImplementedError

    def tool_result(self, tool_call_id, name, content):
        """把单次工具执行结果组装成当前厂商格式的 messages 片段。"""
        raise NotImplementedError


class OpenAICompatibleAdapter(LLMAdapter):
    """对接一切 OpenAI /chat/completions 兼容端点。"""

    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL")
                        or "https://api.openai.com/v1").rstrip("/")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.url = f"{self.base_url}/chat/completions"

    def chat(self, messages, tools=None, tool_choice="auto"):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        return _http_post(self.url, headers, payload)

    def content_text(self, response):
        return response["choices"][0]["message"].get("content") or ""

    def parse_tool_calls(self, response):
        msg = response["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls", []) or []:
            if tc.get("type") != "function":
                continue
            fn = tc["function"]
            calls.append({
                "name": fn["name"],
                "arguments": json.loads(fn.get("arguments") or "{}"),
            })
        return calls

    def assistant_with_tools(self, content, calls):
        ids, tcs = [], []
        for i, c in enumerate(calls):
            cid = f"call_{i}"
            ids.append(cid)
            tcs.append({
                "id": cid,
                "type": "function",
                "function": {
                    "name": c["name"],
                    "arguments": json.dumps(c["arguments"], ensure_ascii=False),
                },
            })
        return ({"role": "assistant", "content": content or "",
                  "tool_calls": tcs}, ids)

    def tool_result(self, tool_call_id, name, content):
        return {"role": "tool", "tool_call_id": tool_call_id,
                "content": content}


class AnthropicAdapter(LLMAdapter):
    """对接 Anthropic Claude 官方 API。"""

    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        self.url = "https://api.anthropic.com/v1/messages"
        self.version = "2023-06-01"

    # Anthropic 工具格式与 OpenAI 略不同：function 外层去掉
    @staticmethod
    def _to_anthropic_tools(tools_openai):
        out = []
        for t in tools_openai:
            f = t["function"]
            out.append({
                "name": f["name"],
                "description": f["description"],
                "input_schema": f["parameters"],
            })
        return out

    def chat(self, messages, tools=None, tool_choice="auto"):
        # 把 OpenAI 风格的 messages 转成 Anthropic（system 提出）
        sys_parts = [m["content"] for m in messages if m["role"] == "system"]
        conv = [m for m in messages if m["role"] != "system"]
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": conv,
        }
        if sys_parts:
            payload["system"] = "\n".join(sys_parts)
        if tools and tool_choice == "auto":
            payload["tools"] = self._to_anthropic_tools(tools)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.version,
        }
        return _http_post(self.url, headers, payload)

    def content_text(self, response):
        return "".join(
            b.get("text", "") for b in response.get("content", [])
            if b.get("type") == "text"
        )

    def parse_tool_calls(self, response):
        calls = []
        for b in response.get("content", []):
            if b.get("type") != "tool_use":
                continue
            calls.append({"name": b["name"], "arguments": b.get("input", {})})
        return calls

    def assistant_with_tools(self, content, calls):
        ids, blocks = [], []
        if content:
            blocks.append({"type": "text", "text": content})
        for c in calls:
            cid = f"tu_{c['name']}"
            ids.append(cid)
            blocks.append({
                "type": "tool_use", "id": cid,
                "name": c["name"], "input": c["arguments"],
            })
        return ({"role": "assistant", "content": blocks}, ids)

    def tool_result(self, tool_call_id, name, content):
        return {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_call_id,
             "content": content},
        ]}


def get_adapter(provider="openai", **kwargs):
    """工厂：provider ∈ {openai, anthropic}；其余参数透传。"""
    provider = (provider or os.environ.get("HMA_LLM", "openai")).lower()
    if provider == "anthropic":
        return AnthropicAdapter(**kwargs)
    return OpenAICompatibleAdapter(**kwargs)


# 让 examples 直接用这套工具声明
TOOLS = HMA_TOOLS_OPENAI
