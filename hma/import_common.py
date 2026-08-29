# -*- coding: utf-8 -*-
"""import_common —— 客户端原生记忆 → HMA 的确定性落库原语。

R49 设计翻转：废弃 external/ 隔离命名空间，改为把原客户端记忆
「拆碎、按内容归类」进 HMA 规范命名空间（User / Project / Other / …）。
每条导入事件携带：
  - tags: ["src:<client>", "imported"] + 可选 extra_tags
  - body 末尾追加 `> 来源: <client> 原生记忆 @ <source_ref>` 溯源行
  - 稳定 eid（由调用方给定，保证重跑幂等，不重复建行）

架构分工（严格对齐 HMA 铁律「理解归 AI，落库归脚本」）：
  - AI（memory-import 技能）判定客户端 + 把原生记忆切成逻辑条目 +
    判定每条归哪个命名空间（User/项目/Other）+ 给定稳定 eid + 给溯源引用。
  - 本原语只做纯确定性写：拼包路径、加标签、追加溯源行、
    派生锚点、调 Memory.write，统一前台 db 自动接住。

注：本模块位于内部包 hma/hma/（与 hma_core 同处），故 `import hma`
解析到该内部包；适配器与 `python -m hma.import_entry` 均可直接
`from hma.import_common import write_imported`。
"""
import os
import re
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hma.hma_core import Memory
from hma.hma_core import derive_anchors


def _lead_line(body, limit=80):
    """取正文里第一条『非标题、非空』内容行作摘要，去列表/引用前缀。

    HMA 的 L1 query() 只匹配 id/title/summary/aliases/tags，不搜正文；
    若 summary 落到 markdown 标题行（如 '# MEMORY'）则该事件 L1 几乎
    不可召回。这里取真正的内容首行，让导入记忆的关键事实能被关键词命中。
    """
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        s = re.sub(r"^[\-\*\+>\s]+", "", s)
        return s[:limit]
    return ""


def write_imported(memory_root, namespace, client, eid, title, body,
                   source_ref, created=None, extra_tags=None):
    """把一条「已理解、已归类」的客户端记忆条目确定性写入 HMA。

    Args:
      memory_root : HMA 记忆根（如 .memory）
      namespace   : 规范命名空间（User / Project / Other …）
      client      : 源客户端标识（claude / gemini / codex / wb …），
                     同时用于 src:<client> 标签与包名
      eid         : 稳定事件 id（同 client+namespace+eid 重跑幂等覆盖）
      title       : 事件标题
      body        : 事件正文（原文，不摘要改写）
      source_ref  : 溯源引用（原客户端记忆文件的路径/位置）
      created     : 可选创建日期（WHERE 过滤键，默认今天）
      extra_tags  : 可选额外标签列表

    Returns:
      落库包的绝对路径（= memory_root/namespace/client）
    """
    pkg_root = os.path.join(memory_root, namespace, client)
    os.makedirs(pkg_root, exist_ok=True)
    mem = Memory(pkg_root)
    full_body = body.rstrip() + "\n\n> 来源: %s 原生记忆 @ %s\n" % (client, source_ref)
    tags = ["src:%s" % client, "imported"] + list(extra_tags or [])
    summary = _lead_line(body) or title
    today = datetime.date.today().isoformat()
    mem.write(
        id=eid,
        title=title,
        summary=summary,
        aliases=[title],
        tags=tags,
        linked=[],
        body=full_body,
        created=created or today,
        updated=today,
        anchors=derive_anchors(full_body),
        trigger="memory-import",
    )
    mem.close()
    return pkg_root
