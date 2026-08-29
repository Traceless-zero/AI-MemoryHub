# -*- coding: utf-8 -*-
"""主题视图派生器 —— 按 daylog设计.md，从 daylog 的 beat 标记机械派生主题视图。

纯正则、零 AI、可随时重建。产出：
  1) 各包的 开发日志.md —— 按 beat 的 linked（仅"…/开发日志"结尾的目标）聚合；
  2) memory/日志/主题索引.md —— 全部 beat 仅按链接（linked）聚合的视图。

安全闸：只重写「不存在」或「首部含派生标记」的文件；
已存在的手写文件（无标记）一律跳过并告警，绝不覆盖。
"""
import datetime
import io
import os
import re
import sys

MARKER = "本文件由脚本派生"
BEAT_HEAD_RE = re.compile(r"^### (\d+) · (.+?) · (\d{1,2}:\d{2})\s*$")
BEAT_COMMENT_RE = re.compile(r"<!--beat(.*?)-->")


def repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        if os.path.isdir(os.path.join(cand, "memory")):
            return cand
    if os.path.isdir(os.path.join(os.getcwd(), "memory")):
        return os.getcwd()
    return here


def _parse_meta(comment):
    linked = ""
    tags = []
    m = re.search(r"linked:([^\s]+)", comment)
    if m:
        linked = m.group(1)
    m = re.search(r"tags:([^\s]+)", comment)
    if m:
        tags = [t for t in m.group(1).split(",") if t]
    return linked, tags


def _first_sentence(body_lines):
    for ln in body_lines:
        s = ln.strip().lstrip("-").strip()
        if not s or s.startswith("touched:"):
            continue
        s = re.sub(r"[#*>`]", "", s).strip()
        cut = re.split(r"(?<=[。！？])", s)[0]
        return (cut[:60] + "…") if len(cut) > 60 else cut
    return ""


def parse_daylog(path, date):
    """返回 beat 列表：[{seq,title,time,touched,linked,tags,summary,date}]。
    单趟扫描，同时支持结构化 ### NN 块与老式「段落 + beat 注释」块，
    同一文件两种形态混排也能各收各的。"""
    with io.open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    beats = []
    cur = None          # 结构化 beat 进行中
    buf = []            # 老式段落缓冲（未见 ### 时的裸文本）
    n_legacy = 0
    fm_depth = 0
    for ln in lines:
        if ln.strip() == "---" and fm_depth < 2:
            fm_depth += 1
            continue
        if fm_depth == 1:
            continue
        h = BEAT_HEAD_RE.match(ln)
        if h:
            cur = {"seq": h.group(1), "title": h.group(2).strip(),
                   "time": h.group(3), "touched": [], "linked": "",
                   "tags": [], "body": [], "date": date}
            buf = []
            continue
        c = BEAT_COMMENT_RE.search(ln)
        if c:
            linked, tags = _parse_meta(c.group(1))
            if cur is not None:
                cur["linked"], cur["tags"] = linked, tags
                cur["summary"] = _first_sentence(cur["body"])
                beats.append(cur)
                cur = None
            else:
                n_legacy += 1
                body = [b for b in buf if b.strip()]
                first = body[0].strip() if body else ""
                beats.append({
                    "seq": "L%d" % n_legacy,
                    "title": (first[:30] + "…") if len(first) > 30 else first,
                    "time": "", "touched": [], "linked": linked, "tags": tags,
                    "body": body, "date": date,
                    "summary": _first_sentence(body),
                })
            buf = []
            continue
        if re.match(r"^##\s", ln) or re.match(r"^#\s", ln):
            continue
        if ln.strip().startswith(">"):
            continue
        t = re.match(r"^- touched:\s*\[(.*)\]", ln)
        if cur is not None and t:
            cur["touched"] = [x.strip() for x in t.group(1).split(",") if x.strip()]
            continue
        if cur is not None:
            cur["body"].append(ln)
        else:
            buf.append(ln)
    return beats


def _fm(title, summary, tags, linked, created, updated):
    return """---
title: %s
summary: %s
tags: [%s]
linked: [%s]
anchors: []
person: []
event_date: "—"
location: []
topic: []
pkage_created: %s
pkage_updated: %s
---
""" % (title, summary, ", ".join(tags), ", ".join(linked), created, updated)


def _entry(b):
    t = "%s · %s" % (b["date"], b["title"])
    if b["time"]:
        t = "%s · %s · %s" % (b["date"], b["time"], b["title"])
    s = " —— %s" % b["summary"] if b["summary"] else ""
    return "- %s%s → daylog-%s#%s" % (t, s, b["date"], b["seq"])


def _write_guarded(path, text):
    """安全闸：不存在 → 写；存在且含派生标记 → 重写；否则跳过。

    注意：标记可能落在正文（front-matter 很长时），故扫整文件而非前 600 字符，
    否则带大 front-matter 的派生文件会被误判为手写而静默跳过。
    """
    if os.path.exists(path):
        with io.open(path, "r", encoding="utf-8") as f:
            head = f.read()
        if MARKER not in head:
            return "skip"
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return "write"


def derive(root, progress=None):
    mem = os.path.join(root, "memory")
    logdir = os.path.join(mem, "日志")
    if not os.path.isdir(logdir):
        return {"devlogs": 0, "skipped": []}
    beats = []
    for name in sorted(os.listdir(logdir)):
        m = re.match(r"^daylog-(\d{4}-\d{2}-\d{2})\.md$", name)
        if m:
            beats.extend(parse_daylog(os.path.join(logdir, name), m.group(1)))

    by_linked = {}
    for b in beats:
        if b["linked"]:
            by_linked.setdefault(b["linked"], []).append(b)

    skipped = []
    n_dev = 0
    for linked, items in sorted(by_linked.items()):
        if not linked.endswith("开发日志"):
            continue
        pkg = linked.split("/")[-2] if "/" in linked else linked
        dates = sorted({b["date"] for b in items})
        log_ids = sorted({"日志/daylog-%s" % d for d in dates})
        text = _fm(
            "%s 开发日志" % pkg,
            "%s 的工程记录聚合视图（脚本派生；详实内容在各日 daylog）。" % pkg,
            ["开发日志", "派生"], log_ids, dates[0], dates[-1])
        text += "\n# %s 开发日志\n\n> %s，手改会被覆盖。详实内容在各日 daylog。\n\n" % (pkg, MARKER)
        items = sorted(items, key=lambda b: (b["date"], b["time"], b["seq"]))
        text += "\n".join(_entry(b) for b in items) + "\n"
        path = os.path.join(mem, *linked.split("/")) + ".md"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        r = _write_guarded(path, text)
        if r == "write":
            n_dev += 1
            if progress:
                progress("topic-views", "派生 %s（%d 条）" % (linked, len(items)))
        else:
            skipped.append(linked)
            if progress:
                progress("topic-views", "跳过手写文件（无派生标记）：%s" % linked)

    today = datetime.date.today().isoformat()
    text = _fm("主题索引",
               "全部 daylog 记录按链接的聚合视图（脚本派生）。",
               ["主题索引", "派生"], [], today, today)
    text += "\n# 主题索引\n\n> %s，手改会被覆盖。详实内容在各日 daylog。\n" % MARKER
    text += "\n## 按链接\n"
    for linked, items in sorted(by_linked.items()):
        text += "\n### %s（%d 条）\n\n" % (linked, len(items))
        text += "\n".join(_entry(b) for b in sorted(
            items, key=lambda b: (b["date"], b["time"], b["seq"]))) + "\n"

    idx_path = os.path.join(logdir, "主题索引.md")
    _write_guarded(idx_path, text)
    if progress:
        progress("topic-views", "派生 日志/主题索引（链接 %d）" % len(by_linked))
    return {"devlogs": n_dev, "skipped": skipped}


def main(argv=None):
    root = repo_root()

    def progress(stage, msg):
        print("[+] " + msg)

    r = derive(root, progress=progress)
    print("[DONE] 开发日志派生 %d 个；跳过手写 %d 个" % (
        r["devlogs"], len(r["skipped"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
