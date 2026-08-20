#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIMH front-matter normalizer (zero third-party deps).

Brings every memory/**/*.md front-matter into SCHEMA.md (front-matter V2)
compliance, mirroring what scripts/core/lint_memory.py checks:

  * delete forbidden top-level keys: id / aliases / features
  * rename created -> pkage_created, updated -> pkage_updated
  * fill missing required fields with empty containers
    (person/location/topic -> {}, event_date -> "", others -> [])
  * convert block-style lists/dicts (tags/linked/anchors) into inline JSON
    single-line (the format the engine's from_markdown actually parses)
  * strip legacy anchors sub-keys: locator / tags

Only the front-matter block (between the leading/closing '---' lines) is
rewritten. The body is never touched.

Default: dry-run (print each file's new front-matter, change nothing).
Pass --apply to write back.
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

REQUIRED = [
    "title", "summary", "tags", "linked", "anchors",
    "person", "event_date", "location", "topic",
    "pkage_created", "pkage_updated",
]
FORBIDDEN = ["id", "aliases", "features"]
# Engine write-back order (hma_core.to_markdown); keeps normalized files tidy.
ORDER = ["title", "summary", "tags", "linked", "anchors",
         "person", "event_date", "location", "topic",
         "pkage_created", "pkage_updated"]


def extract_fm(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    return lines[1:end], end


def coerce_scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    return s


def parse_block(lines, i, base_indent):
    """Recursively parse a YAML-ish block (list or dict) starting at line i
    whose first line is indented by base_indent. Returns (value, next_index)."""
    first = lines[i]
    stripped = first.strip()
    if stripped.startswith("- "):
        items = []
        while i < len(lines):
            line = lines[i]
            if not line.strip().startswith("- "):
                break
            if (len(line) - len(line.lstrip())) != base_indent:
                break
            content = line.strip()[2:].strip()
            j = i + 1
            sub = []
            while j < len(lines) and (len(lines[j]) - len(lines[j].lstrip())) > base_indent:
                sub.append(lines[j])
                j += 1
            if sub:
                sub_indent = len(sub[0]) - len(sub[0].lstrip())
                val, _ = parse_block(sub, 0, sub_indent)
                item = {}
                if ":" in content:
                    k, v = content.split(":", 1)
                    item[k.strip()] = coerce_scalar(v)
                if isinstance(val, dict):
                    item.update(val)
                elif val is not None:
                    item["_"] = val
                items.append(item)
            else:
                items.append(coerce_scalar(content))
            i = j
        return items, i
    else:
        d = {}
        while i < len(lines):
            line = lines[i]
            ind = len(line) - len(line.lstrip())
            if ind < base_indent:
                break
            if ind > base_indent:
                break
            if ":" not in line.strip():
                i += 1
                continue
            k, v = line.strip().split(":", 1)
            k = k.strip()
            v = v.strip()
            j = i + 1
            sub = []
            while j < len(lines) and (len(lines[j]) - len(lines[j].lstrip())) > base_indent:
                sub.append(lines[j])
                j += 1
            if sub:
                sub_indent = len(sub[0]) - len(sub[0].lstrip())
                val, _ = parse_block(sub, 0, sub_indent)
                d[k] = val
            else:
                d[k] = coerce_scalar(v)
            i = j
        return d, i


def collect_fields(fm_lines):
    """Return ordered list of (key, value_or_None_for_block, block_lines_or_None)."""
    fields = []
    i = 0
    n = len(fm_lines)
    while i < n:
        line = fm_lines[i]
        if line[:1] in (" ", "\t"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        if v == "":
            # block value follows
            j = i + 1
            sub = []
            while j < n and (len(fm_lines[j]) - len(fm_lines[j].lstrip())) > 0:
                sub.append(fm_lines[j])
                j += 1
            fields.append((k, None, sub))
            i = j
        else:
            fields.append((k, v, None))
            i += 1
    return fields


def normalize(fm_lines):
    fields = collect_fields(fm_lines)
    raw = {}
    for k, v, block in fields:
        if block is not None:
            if not block:
                # 空块：`key:` 后无缩进内容（老样式 `event_date: ` 等）。按 V2 必填
                # 字段的默认空容器填，避免 parse_block([]) 越界崩溃。
                if k in ("person", "location", "topic"):
                    raw[k] = {}
                elif k == "event_date":
                    raw[k] = ""
                else:
                    raw[k] = []
            else:
                sub_indent = len(block[0]) - len(block[0].lstrip())
                parsed, _ = parse_block(block, 0, sub_indent)
                raw[k] = parsed
        else:
            raw[k] = v

    # rename created/updated -> pkage_*
    if "created" in raw and "pkage_created" not in raw:
        raw["pkage_created"] = raw.pop("created")
    if "updated" in raw and "pkage_updated" not in raw:
        raw["pkage_updated"] = raw.pop("updated")
    # delete forbidden
    for f in FORBIDDEN:
        raw.pop(f, None)

    # strip legacy anchors sub-keys
    if isinstance(raw.get("anchors"), list):
        cleaned = []
        for a in raw["anchors"]:
            if isinstance(a, dict):
                a.pop("locator", None)
                a.pop("tags", None)
            cleaned.append(a)
        raw["anchors"] = cleaned

    # fill missing required with empty containers
    for f in REQUIRED:
        if f not in raw:
            if f in ("person", "location", "topic"):
                raw[f] = {}
            elif f == "event_date":
                raw[f] = ""
            else:
                raw[f] = []

    # serialize
    out = ["---"]
    for k in ORDER:
        val = raw[k]
        if isinstance(val, (list, dict)):
            out.append("%s: %s" % (k, json.dumps(val, ensure_ascii=False)))
        else:
            out.append("%s: %s" % (k, val))
    out.append("---")
    return "\n".join(out)


def main():
    apply = "--apply" in sys.argv[1:]
    memory_root = os.path.join(ROOT, "memory")
    changed = 0
    for dirpath, _, fnames in os.walk(memory_root):
        for fn in sorted(fnames):
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                text = open(fp, encoding="utf-8").read()
            except Exception as e:
                print("READ ERR %s: %s" % (fp, e))
                continue
            parsed = extract_fm(text)
            if parsed is None:
                continue
            fm_lines, end = parsed
            try:
                new_fm = normalize(fm_lines)
            except Exception as e:
                print("NORM ERR %s: %s" % (fp, e))
                continue
            if new_fm == "\n".join(fm_lines):
                continue
            changed += 1
            rel = os.path.relpath(fp, ROOT)
            print("\n=== %s" % rel)
            print(new_fm)
            if apply:
                new_text = new_fm + "\n" + "\n".join(text.splitlines()[end + 1:])
                if not new_text.endswith("\n"):
                    new_text += "\n"
                open(fp, "w", encoding="utf-8").write(new_text)
                print("   -> 已写回")
    print("\n== 改动 %d 个文件（%s）" % (changed, "APPLY" if apply else "DRY-RUN"))


if __name__ == "__main__":
    main()
