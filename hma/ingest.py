"""
HMA 主动收录（ingestion）管线
================================

用户提供一段原始文本，AI（经由通用大模型适配器）执行完整收录流程：

  1. 读取现有事件包摘要（仅用于关联发现，不扫正文）
  2. 让 LLM 决定如何拆分成事件包（遵循 CEMA 凝聚性 + 体积闸门：
     一个包一个知识单元；多个不同主题则拆成多个包）
  3. 为每个包生成结构化元数据（id / title / summary / tags / aliases / body）
  4. 写入 .md 权威源 + 确定性 upsert 索引
  5. 与现有 / 新建包建立双向关联

这是「无状态检索」之外、AI 真正承担「理解」职责的那一环——
而理解所用的模型由通用适配器决定，与具体厂商解耦（OpenAI 兼容 / Anthropic 皆可）。

无 LLM 适配器（未配置 API key）时，退化为单包启发式，保证工具永远可用。
"""

import re
import json
import hashlib

from .hma_core import Memory


def slugify(s):
    """把任意字符串变成合法的 kebab-case 事件包 id。空输入返回 ''。"""
    s = (s or "").strip().lower()
    if not s:
        return ""
    # 保留中文与字母数字，其余折叠为连字符
    s = re.sub(r"[^\w一-鿿]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def build_prompt(existing, text):
    """构造喂给 LLM 的收录提示词。existing: [(id,title,summary), ...]"""
    if existing:
        lines = "\n".join(f"- {i}: {t} — {s}" for i, t, s in existing)
    else:
        lines = "(无)"
    return (
        "你是一个记忆收录引擎，服务于 HMA（Hybrid Memory Architecture）。\n"
        "HMA 把记忆存为「事件包」：每个是一个带 YAML front-matter 的 Markdown 文件。\n"
        "好的事件包满足：①凝聚——一个包只承载一个知识单元；②原子——不是杂物堆；"
        "③尺寸得当——若输入包含多个不同主题，请拆成多个包；④可关联——"
        "与【现有事件包】真正相关时才给出关联。\n\n"
        "【现有事件包（仅用于关联发现，可能为空）】\n"
        f"{lines}\n\n"
        "【待收录的新文本】\n"
        f"{text}\n\n"
        "请只输出一个 JSON 对象（不要任何额外文字、不要 markdown 代码围栏）：\n"
        "{\n"
        '  "packages": [\n'
        '    {"id": "kebab-case-唯一-id", "title": "标题", '
        '"summary": "一句话摘要(<=30字)", "tags": ["标签"], '
        '"aliases": ["别名/同义词"], "body": "# 标题\\n\\n markdown 正文"}\n'
        "  ],\n"
        '  "links": [["id-a", "id-b"], ...]\n'
        "}\n"
        "规则：id 必须 kebab-case 且全局唯一；若新包与某个【现有事件包】真正相关，"
        "才把它写进 links（用现有包的 id）；不得编造不存在的现有 id。"
    )


def _strip_fences(s):
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    return s.strip()


def parse_plan(raw):
    """把 LLM 返回的原文解析成 (packages, links)。可被单测。

    packages: [{"id","title","summary","tags","aliases","body"}, ...]
    links:   [["id-a","id-b"], ...]
    """
    if isinstance(raw, dict):
        data = raw
    else:
        data = json.loads(_strip_fences(raw))
    pkgs = data.get("packages", []) or []
    links = data.get("links", []) or []
    norm = []
    for p in pkgs:
        if not isinstance(p, dict):
            continue
        pid = slugify(p.get("id") or p.get("title") or "")
        if not pid:
            continue
        title = (p.get("title") or pid).strip()
        body = (p.get("body") or title or "").strip()
        if not body.startswith("#"):
            body = f"# {title}\n\n{body}"
        norm.append({
            "id": pid,
            "title": title,
            "summary": (p.get("summary") or "").strip(),
            "tags": list(p.get("tags") or []),
            "aliases": list(p.get("aliases") or []),
            "body": body.rstrip() + "\n",
        })
    return norm, links


def run_ingest(memory, text, adapter=None, scope=None,
                auto_link=True, extra_tags=None):
    """执行完整收录流程，返回人类可读的摘要字符串。

    adapter 为 None 时退化为单包启发式（不调用任何模型 API）。
    """
    text = (text or "").strip()
    if not text:
        return "(empty input)"

    existing = memory.list_summaries()
    existing_ids = {i for i, _, _ in existing}

    norm, links = None, []
    if adapter is not None:
        try:
            resp = adapter.chat(
                [{"role": "user", "content": build_prompt(existing, text)}],
                tools=None, tool_choice="auto",
            )
            raw = adapter.content_text(resp)
            norm, links = parse_plan(raw)
        except Exception as e:
            norm = None  # 落到启发式兜底

    if not norm:
        first = (text.splitlines() or [""])[0].strip() or "note"
        pid = slugify(first) or ("note-" + hashlib.md5(text.encode()).hexdigest()[:8])
        norm = [{
            "id": pid,
            "title": first[:80],
            "summary": text[:120].replace("\n", " "),
            "tags": [scope or "note"],
            "aliases": [],
            "body": f"# {first[:80]}\n\n{text}\n",
        }]

    created = []
    for p in norm:
        tags = list(p["tags"])
        if scope and scope not in tags:
            tags.insert(0, scope)
        for t in (extra_tags or []):
            if t not in tags:
                tags.append(t)
        memory.write(
            id=p["id"], title=p["title"], summary=p["summary"],
            aliases=p["aliases"], tags=tags, body=p["body"],
        )
        created.append(p["id"])

    created_ids = set(created)
    linked = []
    if auto_link and links:
        union = created_ids | existing_ids
        for pair in links:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            a, b = pair
            if a in union and b in union and a != b:
                memory.link(a, b)
                linked.append(f"{a} <-> {b}")

    lines = [f"ingested {len(created)} package(s): {', '.join(created)}"]
    if linked:
        lines.append(f"linked {len(linked)}: " + "; ".join(linked))
    return "\n".join(lines)
