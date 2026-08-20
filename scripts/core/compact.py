# -*- coding: utf-8 -*-
"""compact —— (archive 适配器）HMA 上下文压缩归档的确定性落库原语。

昼夜节律 / 上下文压缩归档（q-0 合规版）：
- 触发由 Agent 判定（上下文窗口将满 / 每日 automation），本脚本只做**确定性写**。
- 落点由 Agent（理解层）按内容判定，传给 --sink：
    daylog   : 叙事/时间线内容 → 追加进 daylog-YYYY-MM-DD.md（沿用 R36/R37 叙事 beat）
    cache    : 纯溢出缓存 → memory/cache/archive/<eid>.md（临时缓存包）
    progress : 项目相关 → memory/项目/<project>/<eid>.md（当前项目进度日志）
- 压缩 = 加法式冷摘要：Agent 生成 condensed summary 写入 sink，权威原文不动。
- 冲突规则（q-0）：默认不碰权威原文；仅当 Agent 传 --conflict-event（新信息与某权威事件
  矛盾）时**覆盖该事件 body**，并追加 `> 修改 @ <ISO>: <intro>` trail（可审计，对应文档 L469-470）。

分工（对齐 CEMA §八原则2 / R34）：理解归 Agent（落点判定 + 冷摘要生成 + 冲突发现），
确定性写归本脚本（拼包路径 / 加标签 / 追加 trail / 刷新索引）。
"""
import os
import re
import sys
import argparse
import datetime
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from hma.hma_core import Memory
from hma.import_common import write_imported
from hma.daylog import append_beat
from hma.hma_core import derive_anchors

SINKS = ("日志", "cache", "progress")
ARCHIVE_CLIENT = "archive"


def _repo_root(root):
    """向上找到 memory/ 目录本身（与引擎 _repo_of 同义，避免引私有 helper）。

    注意：统一前台 db 落在 memory/index.db（即 memory 目录【内】），
    不是 memory 的父目录；故此处返回 memory 目录本身，而非含 memory 的仓库根。
    """
    cur = os.path.abspath(root)
    while True:
        if os.path.basename(cur) in ("memory", ".memory"):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(root)  # 兜底：没找到 memory，原样返回
        cur = parent


def _event_filepath(repo, eid):
    """只读 SELECT index.db（可重建缓存）拿事件 .md 路径；无则 None。"""
    db = os.path.join(repo, "index.db")
    if not os.path.isfile(db):
        return None
    con = sqlite3.connect(db)
    try:
        cur = con.cursor()
        cur.execute("SELECT filepath FROM events WHERE id=?", (eid,))
        row = cur.fetchone()
    finally:
        con.close()
    return row[0] if row else None


def _conflict_overwrite(root, eid, new_body, intro):
    """q-0 冲突规则：覆盖权威事件 body，追加修改 trail；返回结果串或 None（事件不在则降级）。"""
    mem0 = Memory(root)
    try:
        pkg = mem0.read(eid, package_id="")  # 全局定位
    finally:
        mem0.close()
    if not pkg:
        return None
    repo = _repo_root(root)
    rel = _event_filepath(repo, eid)
    if not rel:
        return None
    pkg_dir = os.path.dirname(os.path.join(repo, rel))
    trail = "\n> 修改 @ %s: %s" % (datetime.datetime.now().isoformat(timespec="seconds"), intro)
    full = new_body.rstrip() + trail + "\n"
    mem = Memory(pkg_dir)
    try:
        mem.write(
            id=eid,
            title=pkg.title,
            summary=pkg.summary,
            aliases=pkg.aliases,
            tags=pkg.tags,
            linked=pkg.linked,
            body=full,
            created=pkg.created,
            updated=datetime.date.today().isoformat(),
            anchors=derive_anchors(full),
            trigger="hma-archive-conflict",
        )
    finally:
        mem.close()
    return "conflict:%s (trail appended @ %s)" % (eid, pkg_dir)


def _split_csv(v):
    if not v:
        return []
    return [x.strip() for x in str(v).split(",") if x.strip()]


def _sink_daylog(root, summary, linked, tags, date_str, source):
    rid, n = append_beat(
        os.path.join(root, "日志"),
        summary, linked=linked, tags=tags,
        date_str=date_str, trigger="hma-archive")
    return "日志:%s (beats=%d, src=%s)" % (rid, n, source)


def _sink_cache(root, eid, title, summary, source, linked, tags):
    pkg = write_imported(
        root, "cache", ARCHIVE_CLIENT, eid, title, summary, source,
        extra_tags=["archived"] + tags)
    return "cache:%s" % os.path.join("cache", ARCHIVE_CLIENT, eid)


def _sink_progress(root, project, eid, title, summary, source, linked, tags):
    pkg = write_imported(
        root, "项目", project, eid, title, summary, source,
        extra_tags=["progress"] + tags)
    return "progress:%s" % os.path.join("项目", project, eid)


def main():
    ap = argparse.ArgumentParser(
        description="HMA 上下文压缩归档确定性落库（昼夜节律合规版）")
    ap.add_argument("--root", required=True, help="HMA 记忆根（如 memory）")
    ap.add_argument("--sink", required=False, default=None, choices=SINKS,
                        help="落点：日志/cache/progress（冲突模式 --conflict-event 下可省略）")
    ap.add_argument("--summary", required=True, help="Agent 生成的冷凝摘要/叙事（写进 sink 的正文）")
    ap.add_argument("--source", required=True, help="溢出内容来源（溯源，如 '对话溢出/2026-07-25'）")
    ap.add_argument("--id", default=None, help="cache/progress 落点的稳定 eid")
    ap.add_argument("--title", default=None, help="cache/progress 落点的事件标题")
    ap.add_argument("--date", default=None, help="daylog 落点归属日 YYYY-MM-DD（缺省今天）")
    ap.add_argument("--project", default=None, help="progress 落点的项目包 id（如 hma-design-journal）")
    ap.add_argument("--linked", default="", help="索引侧车 linked（逗号分隔）")
    ap.add_argument("--tags", default="", help="索引侧车 tags（逗号分隔）")
    ap.add_argument("--conflict-event", default=None,
                        help="q-0 冲突：与之矛盾的权威事件 id（传则覆盖该事件 body + trail，忽略 --sink）")
    ap.add_argument("--conflict-intro", default=None,
                        help="冲突 trail 的一句话简介（与 --conflict-event 同传）")
    args = ap.parse_args()

    linked = _split_csv(args.linked)
    tags = _split_csv(args.tags)

    # 非冲突模式必须给定合法落点
    if not args.conflict_event and not args.sink:
        ap.error("--sink 必填（除非传 --conflict-event 进入冲突覆盖模式）")

    # —— q-0 冲突覆盖优先（忽略 sink，写回原事件所在包）——
    if args.conflict_event:
        if not args.conflict_intro:
            ap.error("--conflict-event 须同传 --conflict-intro（trail 一句话简介）")
        res = _conflict_overwrite(args.root, args.conflict_event, args.summary, args.conflict_intro)
        if res is None:
            print("⚠ 冲突事件 %s 不存在，降级为普通落点" % args.conflict_event)
        else:
            print(res)
            return

    # —— 正常按 sink 路由 ——
    if args.sink == "日志":
        if not args.date:
            args.date = datetime.date.today().isoformat()
        print(_sink_daylog(args.root, args.summary, linked, tags, args.date, args.source))
    elif args.sink == "cache":
        if not args.id or not args.title:
            ap.error("cache 落点需 --id 与 --title")
        print(_sink_cache(args.root, args.id, args.title, args.summary, args.source, linked, tags))
    elif args.sink == "progress":
        if not args.project or not args.id or not args.title:
            ap.error("progress 落点需 --project --id --title")
        print(_sink_progress(args.root, args.project, args.id, args.title,
                               args.summary, args.source, linked, tags))


if __name__ == "__main__":
    main()
