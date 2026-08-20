# -*- coding: utf-8 -*-
"""目录结构树生成器（已停用）。

`memory/目录结构树.md` 是等同 index.db 的派生缓存，可由 .md 全量重建，
常驻会污染仓库。用户 2026-08-14 拍板**永久停用生成**——`build_tree` 不再写任何文件。
如需临时恢复：重写本模块生成逻辑即可（无外部依赖，纯 stdlib）。

原逻辑摘要：命名空间 → 包 两级树，包内 .md 不入树，隐私目录 veronica/private 跳过。
"""

import sys


def build_tree(memory_root, out_path=None):
    """生成已停用：不再写 memory/目录结构树.md，返回 None。

    检索永远走 index.db（L1→L2→L3），tree 从不是检索入口；统一索引可由
    `Memory.rebuild_all()` 重建，无需常驻一份人类可读的目录树。
    """
    sys.stderr.write(
        "[tree] 目录结构树.md 生成已停用（派生缓存，等同 index.db，无需常驻）\n")
    return None


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "memory"
    print("tree ->", build_tree(root))
