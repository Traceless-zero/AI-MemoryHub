"""
HMA 命令行接口 —— 对应 MCP 工具接口：
  memory_write / memory_query / memory_link / memory_rebuild

用法：
  python -m hma.cli --root <dir> write  --id X --title T --summary S \
          --tags a,b --aliases "x,y" --linked A,B \
          --person "P1,P2" --anchors '[...]' --event-date 2026-08-11 \
          --body "..."
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


def _parse_json(s, name):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception as e:
        raise SystemExit(f"[hma.cli] --{name} 须为合法 JSON：{e}")


def cmd_write(args):
    # —— AI 侧「填模板 dict → check_kw → render_fm 确定性写回」全链路入口 ——
    # 优先走 --fm-dict（JSON 文件）：AI 只产 front-matter dict，validate_fm 校验
    # （结构 + 四要素变体语义 + 锚点 keywords 双通道 5 维契约），通过后 render_fm
    # 借 EventPackage 序列化写回（正文不丢）。校验不过 → 拒绝落库（fail-closed）。
    if args.fm_dict:
        from hma.fm_schema import validate_fm, render_fm
        with open(args.fm_dict, "r", encoding="utf-8") as f:
            d = json.load(f)
        errs = validate_fm(d, memory_root=args.root if args.fm_cross_pkg else None)
        if errs:
            for e in errs:
                print(e)
            print("[fm_schema] 校验未通过，未写入。")
            sys.exit(1)
        body = args.body or ""
        if args.body_file:
            with open(args.body_file, "r", encoding="utf-8") as f:
                body = f.read()
        ok, md, errs2 = render_fm(d, body, filepath=args.out)
        if not ok:
            for e in errs2:
                print(e)
            print("[fm_schema] render 失败，未写入。")
            sys.exit(1)
        out = args.out or os.path.join(args.root, f"{d.get('id') or args.id}.md")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"written (fm-dict): {out}")
        return
    m = Memory(args.root)
    body = args.body
    if args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as f:
            body = f.read()
    if not body and not sys.stdin.isatty():
        body = sys.stdin.read()
    # 兜底（R-safety）：body 缺省/空且现有文件有非空正文 → 自动回填现有正文，
    # 避免「只改 FM」的更新把既有正文清空（与 MCP memory_write 同策略）。
    # 新建（无现有文件）仍允许空 body；显式清空需直接调 Memory.write(force_empty_body=True)。
    if not body:
        existing = m.read_body(args.id)
        if existing:
            body = existing
    anchors = _parse_json(args.anchors, "anchors")        # C+A 锚点列表 JSON
    features = _parse_json(args.features, "features")     # 实体/属性特征 JSON
    # 平铺路径可选轻校验（--fm-check）：结构级 validate_fm（不含跨包污染语义，
    # 因平铺入参无法表达 list[dict] 四要素形态，只查必填/类型/anchors 双通道）。
    if args.fm_check:
        from hma.fm_schema import validate_fm
        d = {
            "title": args.title or args.id,
            "summary": args.summary or "",
            "tags": _split(args.tags),
            "linked": _split(args.linked),
            "person": _parse_json(args.person, "person") if args.person and args.person.strip().startswith("[") else [],
            "location": _parse_json(args.location, "location") if args.location and args.location.strip().startswith("[") else [],
            "topic": _parse_json(args.topic, "topic") if args.topic and args.topic.strip().startswith("[") else [],
            "event_date": args.event_date or "—",
            "anchors": anchors or [],
        }
        errs = validate_fm(d, memory_root=None)
        if errs:
            for e in errs:
                print(e)
            print("[fm_schema] 校验未通过，未写入。")
            sys.exit(1)
    result = m.write(
        id=args.id, title=args.title or args.id,
        summary=args.summary or "",
        aliases=_split(args.aliases), tags=_split(args.tags),
        linked=_split(args.linked), body=body or "",
        person=_split(args.person) or None,
        location=_split(args.location) or None,
        topic=_split(args.topic) or None,
        event_date=args.event_date or None,
        anchors=anchors, features=features,
        integrity_check=args.integrity_check,
    )
    if args.integrity_check:
        # 写入侧反推：result 为 {"path":..., "warnings":[...]}；
        # warnings 非空 = 刚落库的实体缺独有弧段，需反推用户补独有关键词
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"written: {result}")


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
    w.add_argument("--person", default="", help="参与方/人物（逗号分隔；对话记录用）")
    w.add_argument("--location", default="", help="地点（逗号分隔）")
    w.add_argument("--topic", default="", help="主题词（逗号分隔）")
    w.add_argument("--event-date", default="", help="事件日期 YYYY-MM-DD")
    w.add_argument("--anchors", default="",
                   help="C+A 锚点列表 JSON 数组，如 '[{\"Chapter\":\"对话原文\",\"about\":\"…\",\"tags\":[\"…\"],\"locator\":\"对话原文\"}]'")
    w.add_argument("--features", default="", help="实体/属性特征 JSON 对象")
    w.add_argument("--body", default="")
    w.add_argument("--body-file", default="")
    w.add_argument("--integrity-check", action="store_true",
                   help="写入侧反推：以 JSON 返回 {path, warnings}；warnings 非空=刚落库实体缺独有弧段")
    w.add_argument("--fm-dict", default="",
                   help="AI 侧 front-matter dict（JSON 文件）入口：validate_fm 校验（含 anchors 5 维双通道）→ render_fm 确定性写回；校验不过拒绝落库")
    w.add_argument("--fm-check", action="store_true",
                   help="平铺参数路径可选轻校验：结构级 validate_fm（必填/类型/anchors 双通道），不过拒绝落库")
    w.add_argument("--fm-cross-pkg", action="store_true",
                   help="--fm-dict 时启用跨包污染语义规则（需 index.db，较慢）")
    w.add_argument("--out", default="", help="--fm-dict 时指定输出 .md 路径（默认 <root>/<id>.md）")
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
