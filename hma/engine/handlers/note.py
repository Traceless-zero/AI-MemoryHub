# -*- coding: utf-8 -*-
"""mode: note —— 原始文本 → ingest 管线（通用记忆收录）。

文档头可选键：
  root      落库目录（相对仓库根）
  scope     统一注入的作用域标签（如 project / oc / journal）
  text_ref  外部文本文件路径（无内联正文时从此读）

正文来源：第一个 `@@@ body` 段的内容，或 text_ref 指向的文件。

无 LLM 适配器时 run_ingest 退化为单包启发式，保证永远可用；
这体现「HMA 不是 OC 专用」——任何一段文本都能进记忆库。
"""

import os

from ..registry import register
from ...hma_core import Memory
from ...ingest import run_ingest
from ...llm_adapter import get_adapter


@register("note")
def handle_note(doc, *, root_override=None, base_dir=None,
                repo_root=None, trigger="engine.derive"):
    meta = doc.meta
    root = root_override or (
        meta["root"] if os.path.isabs(meta.get("root", "")) else
        os.path.normpath(os.path.join(repo_root or ".",
                                      meta.get("root") or os.path.join("memory", "notes")))
    )
    base_d = os.path.dirname(doc.path or "")
    text = ""
    if doc.packs:
        text = doc.resolve_body(doc.packs[0], base_dir=base_d)
    elif meta.get("text_ref"):
        ref = meta["text_ref"]
        p = ref if os.path.isabs(ref) else os.path.join(base_d, ref)
        with open(p, encoding="utf-8") as f:
            text = f.read()
    if not text.strip():
        raise ValueError("note 源缺少正文（@@@ body 或 text_ref）")

    mem = Memory(root)
    try:
        # 适配器：设了 HMA_LLM（用户配了真实 LLM key/端点）→ 启用 llm_adapter；
        # 否则退化为单包启发式。这是「skill 方向」的付费/本地后端落点——
        # 零成本 Agent 路径（hma-ingest 技能）与此同构、产出一致。
        adapter = get_adapter() if os.environ.get("HMA_LLM") else None
        summary = run_ingest(mem, text, adapter=adapter, scope=meta.get("scope"))
        mem.rebuild()
    finally:
        mem.close()
    return [summary]
