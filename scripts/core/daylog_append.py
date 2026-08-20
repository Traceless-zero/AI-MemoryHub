# -*- coding: utf-8 -*-
"""daylog 追加器 —— 按 daylog设计.md 的写入协议，把一条 beat 机械落进当天 daylog。

职责切分（AI 零路由）：
  - 脚本负责：daylog 文件创建（含 FM-V2 骨架，title 机械=文件名）、序号自增、时间戳、
    touched 存在性校验、beat 注释拼装、pkage_updated 刷新。
  - AI 负责：正文、--touched / --linked / --tags 的内容。
  - 注意：FM 的 title 字段由脚本按文件名自动填充，AI 既不传也不应手动写它。

用法：
  python daylog_append.py --title "修了 query_anchors 中文参数" \
      --touched "hma/server.py,hma/hma_core.py" \
      --linked "项目/AIMH/开发日志" --tags "读取链路,MCP" \
      --body "正文……"            # 或 --body-file x.md / stdin
  可选：--date 2026-08-15（默认今天）、--time 21:30（默认当前时间）
"""
import argparse
import datetime
import io
import os
import re
import sys

DERIVED_HINT = "memory"


def repo_root():
    """scripts/core/daylog_append.py -> <repo>（其下含 memory/）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        if os.path.isdir(os.path.join(cand, DERIVED_HINT)):
            return cand
    if os.path.isdir(os.path.join(os.getcwd(), DERIVED_HINT)):
        return os.getcwd()
    return here


FM_TEMPLATE = """---
title: daylog-{date}   # 机械派生自文件名（==磁盘文件名去扩展名），AI 不写入此字段
summary: {date} 工作日志
tags: [daylog, {date}]
linked: []
anchors: []
person: [{{"用户": ["我", "用户本人"]}}]
event_date: "{date}"
location: []
topic: []
pkage_created: {date}
pkage_updated: {today}
---

# {date} 工作日志

## 流水
"""


def _daylog_path(root, date):
    return os.path.join(root, DERIVED_HINT, "日志", "daylog-%s.md" % date)


def _touched_exists(root, item):
    """touched 条目可能是记忆包 id（项目/AIMH/开发日志）或代码相对路径。"""
    item = item.strip()
    if not item:
        return True
    cands = [
        os.path.join(root, DERIVED_HINT, item),
        os.path.join(root, DERIVED_HINT, item + ".md"),
        os.path.join(root, item),
    ]
    return any(os.path.exists(c) for c in cands)


def _next_seq(lines):
    mx = 0
    for ln in lines:
        m = re.match(r"^### (\d+) ·", ln)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx + 1


def _insert_pos(lines):
    """## 流水 节的末尾 = 下一个 ## 标题前，或文件末尾。"""
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^## 流水", ln):
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if re.match(r"^## ", lines[j]):
            return j
    return len(lines)


def _bump_updated(text, today):
    if re.search(r"^pkage_updated:.*$", text, flags=re.M):
        return re.sub(r"^pkage_updated:.*$", "pkage_updated: %s" % today, text, flags=re.M)
    return text


def build_beat(seq, title, time_str, touched, linked, tags, body):
    parts = ["### %02d · %s · %s" % (seq, title, time_str)]
    parts.append("- touched: [%s]" % ", ".join(touched))
    body = body.strip("\n")
    if body.strip():
        parts.append(body)
    meta = []
    if linked:
        meta.append("linked:%s" % linked)
    if tags:
        meta.append("tags:%s" % ",".join(tags))
    parts.append("<!--beat%s-->" % (" " + " ".join(meta) if meta else ""))
    return "\n".join(parts) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="向当天 daylog 机械追加一条 beat")
    ap.add_argument("--title", required=True, help="一句标题")
    ap.add_argument("--touched", default="", help="逗号分隔的文件/包路径")
    ap.add_argument("--linked", default="", help="关联记忆包/文件 id")
    ap.add_argument("--tags", default="", help="逗号分隔主题词")
    ap.add_argument("--body", default=None, help="正文（缺省读 --body-file 或 stdin）")
    ap.add_argument("--body-file", default=None)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD，默认今天")
    ap.add_argument("--time", dest="time_str", default=None, help="HH:MM，默认当前时间")
    args = ap.parse_args(argv)

    today = datetime.date.today().isoformat()
    date = args.date or today
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        print("[x] --date 须为 YYYY-MM-DD：%s" % date)
        return 1
    time_str = args.time_str or datetime.datetime.now().strftime("%H:%M")
    if not re.match(r"^\d{1,2}:\d{2}$", time_str):
        print("[x] --time 须为 HH:MM：%s" % time_str)
        return 1

    if args.body is not None:
        body = args.body
    elif args.body_file:
        with io.open(args.body_file, "r", encoding="utf-8") as f:
            body = f.read()
    else:
        body = sys.stdin.read()

    touched = [t.strip() for t in args.touched.split(",") if t.strip()]
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    linked = args.linked.strip()

    root = repo_root()
    path = _daylog_path(root, date)
    created = not os.path.exists(path)
    if created:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = FM_TEMPLATE.format(date=date, today=today)
    else:
        with io.open(path, "r", encoding="utf-8") as f:
            text = f.read()

    lines = text.splitlines()
    pos = _insert_pos(lines)
    if pos is None:
        # 老 daylog 无 ## 流水节：补在文件末尾
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("## 流水")
        pos = len(lines)
        text = "\n".join(lines) + "\n"
        lines = text.splitlines()

    seq = _next_seq(lines)
    beat = build_beat(seq, args.title.strip(), time_str, touched, linked, tags, body)

    head = lines[:pos]
    tail = lines[pos:]
    while head and not head[-1].strip():
        head.pop()
    new_lines = head + ["", beat.rstrip("\n"), ""] + tail
    text = "\n".join(new_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text.endswith("\n"):
        text += "\n"
    text = _bump_updated(text, today)

    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

    rel = os.path.relpath(path, root).replace("\\", "/")
    print("[+] %s #%02d · %s · %s%s" % (
        rel, seq, args.title.strip(), time_str, "（新建文件）" if created else ""))
    for t in touched:
        if not _touched_exists(root, t):
            print("[!] touched 未找到：%s（仅告警，不拦截）" % t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
