# -*- coding: utf-8 -*-
"""daylog 追加器 —— 按 daylog设计.md 的写入协议，把一条 beat 机械落进当天 daylog。

职责切分（AI 零路由）：
  - 脚本负责：daylog 文件创建（含 FM-V2 骨架，title 机械=文件名）、序号自增、时间戳、
    touched 存在性校验、beat 注释拼装、pkage_updated 刷新、FM topic 合并、FM tags 底座强制。
  - AI 负责：正文、--touched / --linked / --tags / --topic 的内容。

daylog FM 规矩（2026-08-29 定稿，daylog设计.md 同步）：
  1. FM tags 恒为固定底座 [daylog, YYYY-MM-DD]——beat 主题词走 beat 标记与 --topic，
     绝不进 FM tags（防词袋化积累：08-13 曾积 29 泛标签劫持他包查询）。追加时机械强制。
  2. topic 两阶段：落库时 --topic "规范名|变体1,变体2" 可选（当天主题已知就填，
     08-15 口径）；未填留 []（不编造）。
  3. topic 合并去重：同日多 beat 带不同 --topic → 按规范名去重合并为多主题日
     （合法形态，列表承载）；同规范名变体取并集。
  4. 治理兜底：存量空 topic 的 daylog 由蒸馏/对齐补齐（08-15 为范本；空壳诚实保留）。

用法：
  python daylog_append.py --title "修了 query_anchors 中文参数" \
      --touched "hma/server.py,hma/hma_core.py" \
      --linked "项目/AIMH/开发日志" --tags "读取链路,MCP" \
      --topic "读取链路接线|memory_resolve,keywords接口" \
      --body "正文……"            # 或 --body-file x.md / stdin
  可选：--date 2026-08-15（默认今天）、--time 21:30（默认当前时间）
  --topic 可重复出现（多主题日）；每个值 = "规范名|变体1,变体2"（变体可省）。
"""
import argparse
import datetime
import io
import json
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


# ---------------------------------------------------------------------------
# daylog FM 规矩实现：topic 合并去重 + tags 底座强制（规矩 1/2/3）
# ---------------------------------------------------------------------------
def _fm_span(lines):
    """FM 边界：首个 --- 与第二个 --- 的行号（含）。无 FM 返回 None。"""
    if not lines or lines[0].strip() != "---":
        return None
    for j in range(1, len(lines)):
        if lines[j].strip() == "---":
            return (0, j)
    return None


def _parse_topic_spec(spec):
    """'规范名|变体1,变体2' → {规范名: [变体...]}；无 | → {规范名: []}。"""
    spec = spec.strip()
    if "|" in spec:
        name, _, vs = spec.partition("|")
        return {name.strip(): [v.strip() for v in vs.split(",") if v.strip()]}
    return {spec: []}


def _topic_field_span(fm_lines):
    """定位 FM 的 topic 字段：返回 (起始行号, 结束行号含)。
    兼容 inline 单行（topic: [...]）与 block 换行式（topic: 下缩进 - 条目）。"""
    for i, ln in enumerate(fm_lines):
        if re.match(r"^topic:", ln):
            val = ln.split(":", 1)[1].strip()
            if val:
                return (i, i)
            j = i + 1
            while j < len(fm_lines) and fm_lines[j].lstrip().startswith("-"):
                j += 1
            return (i, j - 1)
    return (None, None)


def _tags_field_span(fm_lines):
    for i, ln in enumerate(fm_lines):
        if re.match(r"^tags:", ln):
            val = ln.split(":", 1)[1].strip()
            if val:
                return (i, i)
            j = i + 1
            while j < len(fm_lines) and fm_lines[j].lstrip().startswith("-"):
                j += 1
            return (i, j - 1)
    return (None, None)


def _parse_topic_entries(fm_lines, ti, tj):
    """topic 字段既有值 → dict{规范名: [变体]}（inline JSON / block 两种形态兼容）。"""
    existing = {}
    seg = "\n".join(fm_lines[ti:tj + 1]).split(":", 1)[1].strip()
    try:
        parsed = json.loads(seg)
        entries = parsed if isinstance(parsed, list) else [parsed]
    except Exception:
        entries = []
        for ln in fm_lines[ti:tj + 1][1:]:
            s = ln.strip()
            if s.startswith("- "):
                s = s[2:].strip()
            m = re.match(r'^"([^"]+)"\s*:\s*(\[[^\]]*\])\s*$', s) or \
                re.match(r'^([^:{}\[\]]+?)\s*:\s*(\[[^\]]*\])\s*$', s)
            if m:
                try:
                    entries.append({m.group(1).strip('" '): json.loads(m.group(2))})
                except Exception:
                    pass
    for x in entries:
        if isinstance(x, dict):
            for k, v in x.items():
                k = str(k).strip()
                lst = existing.setdefault(k, [])
                for vv in (v or []):
                    sv = str(vv)
                    if sv not in lst:
                        lst.append(sv)
    return existing


def _enforce_tags(text, date):
    """规矩 1：FM tags 底座强制——底座必含 [daylog, date]，总数 ≤9
    （超出修剪为底座 + 前 7 个其余词）。每次追加都执行（自愈存量污染）。"""
    fm_lines = text.splitlines()
    span = _fm_span(fm_lines)
    if not span:
        return text, False
    fa, fb = span
    fm = fm_lines[fa:fb + 1]
    gi, gj = _tags_field_span(fm)
    base = ["daylog", date]
    cur = []
    if gi is not None:
        val = fm[gi].split(":", 1)[1].strip()
        if val:
            try:
                cur = [str(x) for x in json.loads(val)]
            except Exception:
                cur = []
    merged_tags = list(base)
    for t in cur:
        if t not in merged_tags:
            merged_tags.append(t)
    if len(merged_tags) > 9:
        merged_tags = base + [t for t in merged_tags if t not in base][:7]
    new_tags_ln = "tags: " + json.dumps(merged_tags, ensure_ascii=False)
    changed = False
    if gi is not None:
        if fm[gi:gj + 1] != [new_tags_ln]:
            fm[gi:gj + 1] = [new_tags_ln]
            changed = True
    else:
        fm.insert(1, new_tags_ln)
        changed = True
    new_text = "\n".join(fm_lines[:fa] + fm + fm_lines[fb + 1:]) + "\n"
    return new_text, changed


def _merge_topic(text, date, topic_specs):
    """规矩 2/3：合并 --topic 进 FM topic（规范名去重、变体并集）。"""
    fm_lines = text.splitlines()
    span = _fm_span(fm_lines)
    if not span:
        return text, False
    fa, fb = span
    fm = fm_lines[fa:fb + 1]

    ti, tj = _topic_field_span(fm)
    changed = False
    existing = {}
    if ti is not None:
        existing = _parse_topic_entries(fm, ti, tj)
    for spec in topic_specs:
        for k, vs in spec.items():
            lst = existing.setdefault(k, [])
            for v in vs:
                if v not in lst:
                    lst.append(v)
                    changed = True
    if ti is not None:
        # 重写 topic 行（inline 单行 JSON），并移除旧 block 行
        new_topic_ln = "topic: " + json.dumps(
            [{k: v} for k, v in existing.items()], ensure_ascii=False)
        fm[ti:tj + 1] = [new_topic_ln]
        changed = changed or True

    new_text = "\n".join(fm_lines[:fa] + fm + fm_lines[fb + 1:]) + "\n"
    return new_text, changed


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
    ap.add_argument("--tags", default="", help="逗号分隔主题词（进 beat 标记；FM tags 恒为 [daylog, 日期] 底座）")
    ap.add_argument("--topic", action="append", default=None,
                    help="daylog FM topic 规范名（规矩 2/3）：格式 '规范名|变体1,变体2'，可重复；"
                         "合并去重进 FM topic 字段。缺省不动 topic（存量空 topic 由蒸馏/对齐补齐）")
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

    # daylog FM 规矩 1/2/3：topic 合并去重（有 --topic 时）+ tags 底座强制（每次）
    if args.topic:
        specs = [_parse_topic_spec(s) for s in args.topic if s.strip()]
        specs = [s for s in specs if s]
        if specs:
            text, _chg = _merge_topic(text, date, specs)
    text, _ = _enforce_tags(text, date)

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
