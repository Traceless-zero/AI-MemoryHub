# -*- coding: utf-8 -*-
"""生成 memory/ 目录结构树.md（命名空间 → 包 两级，包内 .md 不入树）。

派生缓存，等同 index.db，可由 .md 全量重建。
只做 Orientation（写前归类防重名分叉 / 全局概览 / 索引缺失兜底），
绝不当检索入口（检索永远走 index.db：L1 → L2 → L3）。
"""

import os
import sys

# 外层 hma/ 加入路径，保证 hma.hma_core 可 import
_HMA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HMA not in sys.path:
    sys.path.insert(0, _HMA)

NAMESPACE_DESC = {
    "用户": "用户数据包（偏好 / 身份锚点 / 个人事实）",
    "项目": "用户项目包",
    "原创角色": "OC 角色档案",
    "日志": "每日叙事日志",
    "cache": "压缩归档临时缓存包（hma-archive 溢出落点）",
    "其他": "文章 / 杂项 / 资料文本",
}

# 隐私保护：tree 生成时跳过这些目录（对应原 .gitignore 规则）
_PRIVACY_EXCLUDE = {"veronica", "private"}


def _event_md_files(dirpath):
    if not os.path.isdir(dirpath):
        return []
    out = []
    for fn in sorted(os.listdir(dirpath)):
        if fn.endswith(".md") and not fn.endswith(".tmp") \
           and os.path.isfile(os.path.join(dirpath, fn)):
            out.append(fn)
    return out


def _pkg_summary(pkg_dir):
    """从 index.db 取该包一行摘要（取首个事件 summary，多事件标数量）。"""
    try:
        from hma.hma_core import Memory
        m = Memory(pkg_dir)
        try:
            rows = m.list_summaries()  # (id, title, summary)
        finally:
            m.close()
    except Exception:
        return "（摘要取失败）"
    n = len(rows)
    if n == 0:
        return "（空包）"
    first = rows[0]
    s = (first[2] or first[1] or first[0]).strip()
    if n > 1:
        s = "%s（共 %d 项）" % (s, n)
    if len(s) > 60:
        s = s[:57] + "…"
    return s


def build_tree(memory_root, out_path=None):
    """memory_root：memory 目录。生成 目录结构树.md。"""
    repo = memory_root
    if out_path is None:
        out_path = os.path.join(repo, "目录结构树.md")

    lines = []
    lines.append("# memory/ 目录结构树")
    lines.append("")
    lines.append("> 由 `python -m hma.engine tree` 生成（派生缓存，等同 index.db，可由 .md 全量重建）。")
    lines.append("> 只到「包 / 主题」层级；包内的 `.md` 事件文件不在此列出，只在 index.db 检索（L1 → L2 → L3）。")
    lines.append("")

    def _is_excluded(dirname):
        """隐私保护：跳过含 _PRIVACY_EXCLUDE 词的目录名。"""
        parts = set(os.path.basename(dirname.rstrip(os.sep)).lower() for _ in [1])
        return os.path.basename(dirname.rstrip(os.sep)).lower() in _PRIVACY_EXCLUDE

    top = sorted([
        d for d in os.listdir(repo)
        if os.path.isdir(os.path.join(repo, d))
    ])
    for ns in top:
        ns_path = os.path.join(repo, ns)
        if _is_excluded(ns_path):
            continue
        desc = NAMESPACE_DESC.get(ns, "")
        lines.append("- `%s/`  %s" % (ns, desc))
        for dirpath, dirnames, _files in os.walk(ns_path):
            if _is_excluded(dirpath):
                dirnames[:] = []
                continue
            mds = _event_md_files(dirpath)
            if not mds:
                continue
            pkg_id = os.path.relpath(dirpath, repo).replace(os.sep, "/")
            summary = _pkg_summary(dirpath)
            lines.append("  - `%s/`  %s" % (pkg_id, summary))
        lines.append("")

    body = "\n".join(lines).rstrip() + "\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    return out_path


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "memory"
    print("tree ->", build_tree(root))
