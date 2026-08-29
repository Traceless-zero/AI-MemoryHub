"""HMA —— Hybrid Memory Architecture.

AM 做正文（.md）+ 薄 CEMA 索引（SQLite）。零运行时依赖。
"""

__version__ = "0.1.0"

from .hma_core import EventPackage, Memory  # noqa: F401

__all__ = ["EventPackage", "Memory", "__version__"]
