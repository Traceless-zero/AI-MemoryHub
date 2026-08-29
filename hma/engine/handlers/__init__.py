# -*- coding: utf-8 -*-
"""导入所有 handler 模块以触发自注册（@register）。

新增 mode 时，在本目录新建模块并在此 import 一行即可接入。
"""

from . import packs        # noqa: F401  mode: packs
from . import oc_dossier   # noqa: F401  mode: oc_dossier
from . import note         # noqa: F401  mode: note
