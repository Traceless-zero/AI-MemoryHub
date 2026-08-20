#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIMH memory front-matter linter (zero third-party deps).

Deterministic checker that every memory/**/*.md front-matter conforms to
memory/项目/AIMH-design-journal/SCHEMA.md (front-matter V2).

It reuses hma_core's exact parsing contract (the same from_markdown the engine
uses), so an ERROR here means the engine will actually *silently lose* that
field on read -- the single most dangerous class of "AI filled FM wrong".

Exit code != 0 if any ERROR-level violation is found.

Usage:
    python scripts/core/lint_memory.py            # scan memory/ from project root
    python scripts/core/lint_memory.py --root X   # scan a custom memory root
    python scripts/core/lint_memory.py --quiet    # only print files with errors
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hma.hma_core import EventPackage, _four_to_list  # noqa: E402
from hma.fm_schema import check_kw, check_kw_warn  # noqa: E402

REQUIRED = [
    "title", "summary", "tags", "linked", "anchors",
    "person", "event_date", "location", "topic",
    "pkage_created", "pkage_updated",
]

# Directories excluded from the default scan: they are spec docs / demo fixtures,
# not AI-live event packages. Use --all to include them (migration audit).
EXCLUDE_DIRS = ["AIMH-design-journal", "样式demo"]
FORBIDDEN = {
    "id": "身份由文件路径派生",
    "aliases": "折进四要素 dict 变体数组",
    "features": "折进四要素 dict 变体数组",
    "created": "用 pkage_created",
    "updated": "用 pkage_updated",
}
LIST_FIELDS = ["tags", "linked"]
DICT_OR_LIST_FIELDS = ["person", "location", "topic", "anchors"]


def extract_fm(text):
    """Same boundary rule as EventPackage.from_markdown: leading '---' line,
    closing independent '---' line."""
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
    return "\n".join(lines[1:end])


def top_keys(fm_text):
    keys = []
    for line in fm_text.splitlines():
        if line[:1] in (" ", "\t"):  # indented -> not a top-level key
            continue
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            continue
        keys.append(s.split(":", 1)[0].strip())
    return keys


def _strip_comment(s):
    """去掉行尾 YAML 风格注释 ` #...`（引号内的 # 保留），与引擎 _parse_fm 一致。"""
    out = []
    in_q = False
    for i, c in enumerate(s):
        if c == '"' and (i == 0 or s[i - 1] != '\\'):
            in_q = not in_q
        if c == '#' and not in_q and (i == 0 or s[i - 1] in ' \t'):
            break
        out.append(c)
    return "".join(out).rstrip()


def inline_value_head(fm_text, field):
    """Return the value right after 'field:' on its top-level line.
    '' / '""' means block-style or empty (engine reads it as empty)."""
    for line in fm_text.splitlines():
        if line[:1] in (" ", "\t"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.strip() == field:
            return _strip_comment(v).strip()
    return None


def lint_file(fp, text):
    errs = []
    warns = []
    fm = extract_fm(text)
    if fm is None:
        warns.append("WARN 无 front-matter 块（非事件包文档？）")
        return errs, warns
    keys = top_keys(fm)

    # 1. required fields present
    for r in REQUIRED:
        if r not in keys:
            errs.append("ERROR 缺必填字段: %s" % r)

    # 2. forbidden fields absent
    for f, reason in FORBIDDEN.items():
        if f in keys:
            errs.append("ERROR 禁写字段 %s（%s）" % (f, reason))

    # 3. inline JSON 单行 或 block 换行式 均可；仅禁止「既非 JSON 单行也非 block」
    #    的裸标量脏写法（会被引擎读丢）。真正的「静默丢失」由下方第 5 条
    #    引擎交叉校验把关（block 现已被引擎正确解析）。
    for f in LIST_FIELDS + DICT_OR_LIST_FIELDS:
        head = inline_value_head(fm, f)
        if head is None:
            continue  # missing -> already reported above
        head_clean = head.strip().strip('"')  # 容忍 "" 空值写法
        if head_clean == "":
            continue  # block 换行式（引擎现已支持，非空则正常解析）或空值
        if not head.startswith(("[", "{")):
            errs.append("ERROR %s 写法非法（须 [..] / {..} 单行 JSON，或 block 换行式；"
                        "裸标量会被引擎读丢）" % f)

    # 4. anchors legacy sub-keys
    if "locator:" in fm:
        errs.append("ERROR anchors 含旧 locator: 子键（V2 无 locator）")

    # 5. cross-check with the engine's actual parsing
    try:
        pkg = EventPackage.from_markdown(text, fp)
        if not isinstance(pkg.person, dict):
            errs.append("ERROR person 经引擎解析非 dict（已被静默读丢）")
        if not isinstance(pkg.location, dict):
            errs.append("ERROR location 经引擎解析非 dict（已被静默读丢）")
        if not isinstance(pkg.topic, dict):
            errs.append("ERROR topic 经引擎解析非 dict（已被静默读丢）")
        if not isinstance(pkg.tags, list):
            errs.append("ERROR tags 经引擎解析非 list（已被静默读丢）")
        if not isinstance(pkg.linked, list):
            errs.append("ERROR linked 经引擎解析非 list（已被静默读丢）")
        if isinstance(pkg.anchors, list):
            for a in pkg.anchors:
                if isinstance(a, dict) and ("locator" in a or "tags" in a):
                    errs.append("ERROR anchor 含旧 locator/tags 子键")
        # keywords 双通道完整性契约（硬过滤）：叙事5维(故事书) / 概念5维(学术书) 各缺一则 ERROR
        # 派生文件（含"本文件由脚本派生"标记，如 日志/主题索引.md）跳过——其锚点 keywords
        # 由派生脚本生成且恒为空（derive_topic_views 不产 keywords），按手写契约校验必然
        # ERROR；回填又会被派生覆盖。派生文件只查结构，不查内容 5 维（2026-08-19 C3）。
        if "本文件由脚本派生" not in text[:600]:
            d = {
                "anchors": pkg.anchors,
                "person": _four_to_list(pkg.person),
                "location": _four_to_list(pkg.location),
                "event_date": pkg.event_date,
            }
            errs.extend(check_kw(d))
            warns.extend(check_kw_warn(d))
    except Exception as e:  # pragma: no cover
        warns.append("WARN 引擎解析异常: %s" % e)

    return errs, warns


def main():
    args = sys.argv[1:]
    quiet = "--quiet" in args
    scan_all = "--all" in args
    root = ROOT
    for a in args:
        if a.startswith("--root="):
            root = os.path.abspath(a.split("=", 1)[1])
        elif a == "--root" and args.index(a) + 1 < len(args):
            root = os.path.abspath(args[args.index(a) + 1])
    memory_root = os.path.join(root, "memory")

    scanned = 0
    total_err = 0
    total_warn = 0
    reports = []

    if not os.path.isdir(memory_root):
        print("memory 目录不存在: %s" % memory_root)
        sys.exit(2)

    for dirpath, _, fnames in os.walk(memory_root):
        for fn in sorted(fnames):
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(dirpath, fn)
            if not scan_all:
                _rel = os.path.relpath(fp, memory_root).replace(os.sep, "/")
                if any(("/" + ex + "/") in ("/" + _rel + "/") for ex in EXCLUDE_DIRS):
                    continue
            try:
                text = open(fp, encoding="utf-8").read()
            except Exception as e:
                reports.append((fp, ["ERROR 无法读取: %s" % e], []))
                total_err += 1
                scanned += 1
                continue
            errs, warns = lint_file(fp, text)
            scanned += 1
            if errs:
                total_err += len(errs)
            if warns:
                total_warn += len(warns)
            if errs or (warns and not quiet):
                reports.append((fp, errs, warns))

    print("AIMH front-matter lint — 扫描 %d 个 .md" % scanned)
    for fp, errs, warns in reports:
        rel = os.path.relpath(fp, root)
        if errs or warns:
            print("\n%s %s" % ("✗" if errs else "•", rel))
            for e in errs:
                print("   %s" % e)
            for w in warns:
                print("   %s" % w)
    print("\n== 结果：ERROR=%d  WARN=%d  扫描=%d" % (total_err, total_warn, scanned))
    sys.exit(1 if total_err else 0)


if __name__ == "__main__":
    main()
