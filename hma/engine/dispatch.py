# -*- coding: utf-8 -*-
"""HMA 通用引擎入口（内容即数据，引擎即代码）。

    python -m hma.engine modes                 # 列出已注册的 mode
    python -m hma.engine derive <root>         # 重派生章级锚点
    python -m hma.engine query <root> <q>      # 确定性检索（关联发现用）
    python -m hma.engine query_anchors <root> <q>  # L2 章级检索
    python -m hma.engine install/uninstall <pkg>   # 装卸记忆包索引
    python -m hma.engine rebuild-all <root>    # 全量重建索引 + 目录树
    python -m hma.engine tree <root>           # 生成目录结构树（已停用）

记忆直接落 `memory/`（单一权威存储），不再经 sources/ 中间格式。
daylog 由 scripts/core/daylog_append.py 机械追加（单 daylog 路线，详见 daylog设计.md）。
"""

import os
import sys
import argparse

from . import handlers  # noqa: F401  触发 handler 自注册
from .registry import dispatch, available_modes
from ..hma_core import Memory
from ..hma_core import derive_anchors, merge_anchors


def repo_root():
    """仓库根：.../hma（engine 位于 .../hma/hma/engine/）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cmd_modes(a):
    print("已注册 mode：", ", ".join(available_modes()))


def _cmd_derive(a):
    """对 built 记忆重派生章级锚点（扫描 `##` 标题树，写回）。

    默认【合并】语义（见 merge_anchors）：派生打底 + 保留用户手写修改——
      - 正文新 ## → 补派生；已有 ## 被手改 → 留用户版；
      - 正文删 ## → 删锚点；用户锚定子节(###) → 留。
    加 --force 则退化为旧行为：整组覆盖为纯派生版（丢弃手写）。
    幂等：合并结果与现存一致则跳过写。
    target 必须是已落库（直接含事件 .md）的 root 目录。
    """
    tgt = a.target
    # 只接受已落库目录（直接含事件 .md），不再有 sources/ 中间格式
    if not (os.path.isdir(tgt) and any(
            fn.endswith(".md") and not fn.endswith(".tmp")
            and os.path.isfile(os.path.join(tgt, fn))
            for fn in os.listdir(tgt))):
        sys.stderr.write(
            "[abort] 目标不是已落库目录（须直接含事件 .md）：%s\n" % tgt)
        return
    root, label = tgt, tgt

    mem = Memory(root)
    try:
        n_write = 0
        for rid, _t, _g, _u in mem.list_all():
            pkg = mem.read(rid)
            if not pkg:
                continue
            if getattr(a, "force", False):
                anchors = derive_anchors(pkg.body)          # 全量覆盖派生
            else:
                anchors = merge_anchors(pkg.anchors, pkg.body)  # 合并（打底+留手改）
            if pkg.anchors == anchors:      # 已一致 → 跳过，幂等
                continue
            mem.write(
                id=rid, title=pkg.title, summary=pkg.summary,
                aliases=pkg.aliases, tags=pkg.tags, linked=pkg.linked,
                body=pkg.body, anchors=anchors,
                created=pkg.created, updated=pkg.updated,
                trigger="engine.derive",
            )
            n_write += 1
        mem.rebuild()
    finally:
        mem.close()
    if getattr(a, "force", False):
        tail = "，--force 全量覆盖"
    else:
        tail = "，合并模式"
    print(f"派生锚点完成：更新 {n_write} 个包（root={label}{tail}）")


def _cmd_query(a):
    """确定性检索已落库事件包（供 skill 方向收录做关联发现）。"""
    mem = Memory(a.root)
    try:
        if getattr(a, "all", False):
            rows = mem.query(a.q, top_k=a.top_k, package_id="")
        elif getattr(a, "package", None):
            rows = mem.query(a.q, top_k=a.top_k, package_id=a.package)
        else:
            rows = mem.query(a.q, top_k=a.top_k)
    finally:
        mem.close()
    if not rows:
        print("(no match)")
        return
    for rid, title, summary, score in rows:
        print("%4d  %-28s | %s | %s" % (score, rid, title, summary))


def _cmd_query_anchors(a):
    """L2 检索：按锚点（## 章节标题）精确定位章节。"""
    mem = Memory(a.root)
    try:
        if getattr(a, "all", False):
            rows = mem.query_anchors(a.q, top_k=a.top_k, package_id="")
        elif getattr(a, "package", None):
            rows = mem.query_anchors(a.q, top_k=a.top_k, package_id=a.package)
        else:
            rows = mem.query_anchors(a.q, top_k=a.top_k)
    finally:
        mem.close()
    if not rows:
        print("(no match)")
        return
    for rid, title, _summary, locator, score in rows:
        print("%4d  %-28s | %s | @@@ %s" % (score, rid, title, locator))


# ---------------------------------------------------------------------------
# 统一 db 装卸：一个脚本直接装/卸某个记忆文件夹
# ---------------------------------------------------------------------------
def _cmd_install(a):
    """把一个记忆包（直接含事件 .md）装入统一索引。"""
    root = a.root if a.root else a.pkg_dir   # 默认从 pkg_dir 推导仓库根
    mem = Memory(root)
    try:
        n = mem.install(a.pkg_dir, rm=a.rm)
    finally:
        mem.close()
    print("install %s -> %d 条索引（仓库根 %s）" % (a.pkg_dir, n, mem.repo))


def _cmd_uninstall(a):
    """从统一索引卸下某个记忆包（按 package_id）。"""
    mem = Memory(a.root)
    try:
        pid = mem.uninstall(a.package_id, rm=a.rm)
    finally:
        mem.close()
    print("uninstall %s 完成（仓库根 %s）" % (pid, mem.repo))


def _cmd_rebuild_all(a):
    """遍历仓库根下所有包，全量重建统一索引（不再生成目录结构树）。"""
    mem = Memory(a.root)
    try:
        n = mem.rebuild_all()
    finally:
        mem.close()
    print("rebuild-all -> %d 条索引（仓库根 %s）" % (n, mem.repo))


def _cmd_tree(a):
    """目录结构树生成已停用（派生缓存，等同 index.db，无需常驻）。"""
    print("[tree] 目录结构树.md 生成已停用（见 SCHEMA 约定）")




def build_parser():
    p = argparse.ArgumentParser(prog="hma.engine",
                                description="HMA 通用引擎入口（内容即数据）")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("modes", help="列出已注册 mode")
    m.set_defaults(func=_cmd_modes)
    dv = sub.add_parser("derive",
                        help="重派生章级锚点（合并：派生打底+保留手写；--force 全量覆盖）")
    dv.add_argument("target",
                      help="已落库目录（直接含事件 .md）")
    dv.add_argument("--force", action="store_true",
                    help="全量覆盖为纯派生版（丢弃手写修改）；默认合并模式")
    dv.set_defaults(func=_cmd_derive)
    qp = sub.add_parser("query",
                        help="确定性检索已落库事件包（关联发现用）")
    qp.add_argument("root", help="落库根目录（如 memory/notes）；--all 时忽略")
    qp.add_argument("q", help="查询关键词")
    qp.add_argument("--top-k", type=int, default=5, help="返回条数")
    qp.add_argument("--all", action="store_true",
                    help="跨所有包全局检索（忽略 root 作用域）")
    qp.add_argument("--package", help="只检索指定 package_id（如 原创角色/luzhao）")
    qp.set_defaults(func=_cmd_query)

    qa = sub.add_parser("query_anchors",
                        help="L2 检索：按锚点（## 章节标题）精确定位章节")
    qa.add_argument("root", help="落库根目录；--all 时忽略")
    qa.add_argument("q", help="锚点关键词")
    qa.add_argument("--top-k", type=int, default=5, help="返回条数")
    qa.add_argument("--all", action="store_true",
                    help="跨所有包全局检索锚点（忽略 root 作用域）")
    qa.add_argument("--package", help="只检索指定 package_id（如 原创角色/luzhao）")
    qa.set_defaults(func=_cmd_query_anchors)

    ai = sub.add_parser("install",
                        help="把一个记忆包（直接含事件 .md）装入统一索引")
    ai.add_argument("pkg_dir", help="记忆包路径（其下须直接含事件 .md）")
    ai.add_argument("--root", default=None,
                    help="仓库根（含 memory 的目录，默认从 pkg_dir 推导）")
    ai.add_argument("--rm", action="store_true",
                    help="装完后删除【源】文件夹（内容已进统一索引）")
    ai.set_defaults(func=_cmd_install)

    au = sub.add_parser("uninstall",
                        help="从统一索引卸下某个记忆包（按 package_id）")
    au.add_argument("package_id", help="包标识，如 原创角色/luzhao")
    au.add_argument("--root", default="memory",
                    help="仓库根目录（含 index.db 的 memory，默认 memory）")
    au.add_argument("--rm", action="store_true",
                    help="同时删除磁盘上的包文件夹（<root>/<package_id>）")
    au.set_defaults(func=_cmd_uninstall)

    ar = sub.add_parser("rebuild-all",
                        help="遍历仓库根下所有包，全量重建统一索引（不再生成目录结构树）")
    ar.add_argument("--root", default="memory",
                    help="仓库根目录（含 index.db 的 memory，默认 memory）")
    ar.set_defaults(func=_cmd_rebuild_all)

    t = sub.add_parser("tree",
                        help="目录结构树生成已停用（派生缓存，等同 index.db）")
    t.add_argument("--root", default="memory",
                    help="仓库根目录（含 memory 的目录，默认 memory）")
    t.set_defaults(func=_cmd_tree)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
