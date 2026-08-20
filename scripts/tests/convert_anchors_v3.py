#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将全库 .md 的 anchors front-matter 重排为 v3 格式：
每锚点 3 行（Chapter/about/keywords 各占一行），keywords 为单行内联 JSON。

只在 front-matter（首个 ---...--- 块）内定位并替换 anchors 块，正文不动。
逐文件 round-trip 校验（anchors + keywords 完全一致）后才落盘。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hma.hma_core import EventPackage

ROOT = "memory"
# 吃掉「anchors:」整段：从 anchors: 一直匹配到下一个顶层字段（非空、顶格行）或 fm 末尾；
# 中间允许锚点之间有空行（v2 block 习惯在锚点间留空行）。
ANCHORS_BLOCK_RE = re.compile(r"^anchors:.*?(?=\n[^\s]|\Z)", re.S | re.M)
FM_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*\n", re.S)


def anchors_equal(a, b):
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x.get("Chapter") != y.get("Chapter"):
            return False
        if x.get("about") != y.get("about"):
            return False
        if (x.get("keywords") or []) != (y.get("keywords") or []):
            return False
    return True


def main():
    ok = skip = err = 0
    for dirpath, _, files in os.walk(ROOT):
        for fn in sorted(files):
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(dirpath, fn)
            txt = open(fp, encoding="utf-8").read()
            m = FM_RE.match(txt)
            if not m:
                continue
            if "anchors:" not in m.group(1):
                continue
            try:
                pkg = EventPackage.from_markdown(txt, filepath=fp)
            except Exception as e:
                print("  ERR_PARSE", fp, e)
                err += 1
                continue
            if not pkg.anchors:
                # 无锚点：anchors: [] 即可，跳过
                continue
            new_block = "\n".join(pkg._fmt_anchors_block())
            fm = m.group(1)
            if ANCHORS_BLOCK_RE.search(fm) is None:
                print("  ERR_NO_MATCH", fp)
                err += 1
                continue
            new_fm = ANCHORS_BLOCK_RE.sub(new_block, fm, count=1)
            new_txt = txt[: m.start(1)] + new_fm + txt[m.end(1):]
            # round-trip 校验
            try:
                pkg2 = EventPackage.from_markdown(new_txt, filepath=fp)
            except Exception as e:
                print("  ERR_REPARSE", fp, e)
                err += 1
                continue
            if not anchors_equal(pkg.anchors, pkg2.anchors or []):
                print("  ERR_ROUNDTRIP", fp)
                err += 1
                continue
            if new_txt == txt:
                skip += 1
                continue
            open(fp, "w", encoding="utf-8").write(new_txt)
            ok += 1
            print("  OK", fp, "anchors=", len(pkg.anchors))
    print(f"\n转换完成: ok={ok} skip={skip} err={err}")


if __name__ == "__main__":
    main()
