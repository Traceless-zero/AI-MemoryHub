"""
HMA 命令行接口 —— 对应 MCP 工具接口：
  memory_write / memory_query / memory_link / memory_rebuild

用法：
  python -m hma.cli --root <dir> write  --id X --title T --summary S \
          --tags a,b --aliases "x,y" --linked A,B --body "..."
  python -m hma.cli --root <dir> query  "关键词" --top-k 5
  python -m hma.cli --root <dir> link   A B
  python -m hma.cli --root <dir> rebuild
  python -m hma.cli --root <dir> show   X
  python -m hma.cli --root <dir> list
"""

import argparse
import sys
import os
import json
from hma.hma_core import Memory


def _split(s):
    if s is None:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def cmd_write(args):
    m = Memory(args.root)
    body = args.body
    if args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as f:
            body = f.read()
    if not body and not sys.stdin.isatty():
        body = sys.stdin.read()
    path = m.write(
        id=args.id, title=args.title or args.id,
        summary=args.summary or "",
        aliases=_split(args.aliases), tags=_split(args.tags),
        linked=_split(args.linked), body=body or "",
    )
    print(f"written: {path}")


def cmd_query(args):
    m = Memory(args.root)
    hits = m.query(args.q, top_k=args.top_k, use_vector=args.vector)
    if not hits:
        print("(no match)")
        return
    for rid, title, summary, score in hits:
        print(f"[{score:>3}] {rid}  —  {title}")
        if summary:
            print(f"        {summary}")


def cmd_link(args):
    m = Memory(args.root)
    m.link(args.a, args.b)
    print(f"linked: {args.a} <-> {args.b}")


def cmd_rebuild(args):
    m = Memory(args.root)
    n = m.rebuild()
    print(f"rebuilt index: {n} event packages")


def cmd_show(args):
    m = Memory(args.root)
    pkg = m.read(args.id)
    if not pkg:
        print(f"(not found: {args.id})")
        return
    print(pkg.to_markdown())


def cmd_list(args):
    m = Memory(args.root)
    for rid, title, tags, updated in m.list_all():
        print(f"{updated}  {rid}  {title}  {tags}")


def cmd_ingest(args):
    m = Memory(args.root)
    text = args.text
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read()
    adapter = None
    if not args.no_llm:
        try:
            from hma.llm_adapter import get_adapter
            adapter = get_adapter(model=args.model)
        except Exception as e:
            print(f"[warn] LLM adapter unavailable, fallback: {e}",
                  file=sys.stderr)
            adapter = None
    from hma.ingest import run_ingest
    print(run_ingest(m, text, adapter=adapter,
                        scope=args.scope, auto_link=not args.no_link))


def build_parser():
    p = argparse.ArgumentParser(prog="hma", description="Hybrid Memory Architecture CLI")
    p.add_argument("--version", action="version", version=f"hma {__import__('hma').__version__}")
    p.add_argument("--root", default="memory", help="记忆库根目录（含子包/事件 .md）；默认 memory/ 仓库根，repo 级全局检索")
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("write", help="写/改一个事件包")
    w.add_argument("--id", required=True)
    w.add_argument("--title", default="")
    w.add_argument("--summary", default="")
    w.add_argument("--tags", default="")
    w.add_argument("--aliases", default="")
    w.add_argument("--linked", default="")
    w.add_argument("--body", default="")
    w.add_argument("--body-file", default="")
    w.set_defaults(func=cmd_write)

    q = sub.add_parser("query", help="确定性检索")
    q.add_argument("q")
    q.add_argument("--top-k", type=int, default=5)
    q.add_argument("--vector", action="store_true")
    q.set_defaults(func=cmd_query)

    l = sub.add_parser("link", help="双向关联两个事件包")
    l.add_argument("a")
    l.add_argument("b")
    l.set_defaults(func=cmd_link)

    r = sub.add_parser("rebuild", help="从 .md 重建索引")
    r.set_defaults(func=cmd_rebuild)

    s = sub.add_parser("show", help="打印一个事件包的完整 .md")
    s.add_argument("id")
    s.set_defaults(func=cmd_show)

    ls = sub.add_parser("list", help="列出所有事件包")
    ls.set_defaults(func=cmd_list)

    ing = sub.add_parser("ingest", help="主动收录：粘贴文本，AI 拆分+写入+关联")
    ing.add_argument("text", nargs="?", default="", help="待收录文本（或用管道/重定向）")
    ing.add_argument("--scope", default=None, help="作用域标签，加进每个新包的 tags")
    ing.add_argument("--model", default=None, help="覆盖默认模型名")
    ing.add_argument("--no-llm", action="store_true", help="跳过 LLM，用单包启发式")
    ing.add_argument("--no-link", action="store_true", help="不做自动关联")
    ing.set_defaults(func=cmd_ingest)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
