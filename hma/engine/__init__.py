# -*- coding: utf-8 -*-
"""hma.engine —— 通用记忆引擎（内容即数据，引擎即代码）。

记忆直接落 `memory/`（单一权威存储），不再经 sources/ 中间格式。

扩展点（分支接口）：
    from hma.engine import register
    @register("your_mode")
    def handler(doc, *, root_override=None, base_dir=None,
                repo_root=None, trigger="engine.derive"): ...

HMA 不是 OC 专用：OC 装卸只是 packs / oc_dossier 两个 handler 的应用。
"""

from .registry import register, dispatch, available_modes, HANDLERS  # noqa: F401
from . import handlers  # noqa: F401  触发 handler 自注册

__all__ = [
    "register", "dispatch", "available_modes", "HANDLERS",
]
