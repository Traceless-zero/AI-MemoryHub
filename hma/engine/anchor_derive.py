# -*- coding: utf-8 -*-
"""anchor_derive —— 兼容性薄壳。

真实实现已迁至 `hma.hma_core`（纯 stdlib、确定性、OC 无关，
供 EXE 打包安全复用，避免拽入 `hma.engine` 的 dispatch/handlers 重依赖）：

    from hma.engine.anchor_derive import derive_anchors   # 仍可用
    from hma.engine.anchor_derive import merge_anchors    # 合并语义（派生打底+留手改）

行为与原实现一致：`derive_anchors` 扫描 `##` 标题树生成章级锚点，
`merge_anchors` 把"自动派生"与"用户手写"按 locator 合并。
"""
from ..hma_core import derive_anchors, merge_anchors

__all__ = ["derive_anchors", "merge_anchors"]
