# -*- coding: utf-8 -*-
"""mode: packs —— 显式清单落库（最通用的 handler）。

源文件里逐个写死事件包（id/title/summary/aliases/tags/anchors/body），
外加一段 `@@@ links` 声明关联。本 handler 把它们原样落库 + 建关联。

这是「内容即数据」的直接体现：原先 build_luzhao.py / build_mcu_rich.py /
build_veronica.py 里硬编码在 Python 常量中的所有内容，全部下沉为
sources/*.md 的数据；引擎不再随主题增长。
"""

import os

from ..registry import register
from ...hma_core import Memory
from ..anchor_derive import derive_anchors


def _resolve_root(root, base_dir):
    if os.path.isabs(root):
        return root
    # 相对路径按仓库根解析（base_dir 传入时优先）
    return os.path.normpath(os.path.join(base_dir or ".", root))


@register("packs")
def handle_packs(doc, *, root_override=None, base_dir=None,
                 repo_root=None, trigger="engine.derive"):
    root = root_override or _resolve_root(doc.root, repo_root)
    if not root:
        raise ValueError("packs 源缺少 root（落库目录）")

    # 关联真相：每个包自带 linked 为首选；`@@@ links` 段（若有）并入。
    # 一步到位写入 linked → 重复构建对同一内容为真正幂等（不产生 changes 噪声），
    # 且避免「先写空 linked 再 link() 回填」造成的中间态与事件抖动。
    adj = {p["id"]: list(p.get("linked", [])) for p in doc.packs}
    for a, b in doc.links:
        if a in adj and b not in adj[a]:
            adj[a].append(b)
        if b in adj and a not in adj[b]:
            adj[b].append(a)

    mem = Memory(root)
    written = []
    try:
        for p in doc.packs:
            body = doc.resolve_body(p, base_dir=os.path.dirname(doc.path or ""))
            # 锚点真相：包显式给了 anchors 就尊重（如 veronica 手写 8 锚点）；
            # 否则从正文 `##` 标题树确定性派生（章级、可全量重建）。
            anchors = p.get("anchors") or []
            if not anchors and body:
                anchors = derive_anchors(body)
            mem.write(
                id=p["id"],
                title=p.get("title", p["id"]),
                summary=p.get("summary", ""),
                aliases=p.get("aliases", []),
                tags=p.get("tags", []),
                linked=adj.get(p["id"], []),
                anchors=anchors,
                body=body,
                trigger=trigger,
            )
            written.append(p["id"])
        # 索引与 .md 权威源对齐（幂等）
        mem.rebuild()
    finally:
        mem.close()

    return written
