"""把 memory/ 下所有 .md 的 anchors 转为多行 block 格式（稳健版）。

只在 front-matter 区域内定位 `anchors:` 条目并整段替换，避免被正文里的
`anchors: [...]` 示例代码误导。逐文件 round-trip 验证（anchors 与 keywords
完全一致）才落盘。已为 block 的文件幂等（替换成相同内容）；无 anchors 的跳过。
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from hma.hma_core import EventPackage

MEM = "memory"


def convert_file(fp):
    txt = open(fp, encoding="utf-8").read()
    if "本文件由脚本派生" in txt[:600]:
        return "skip_derived"
    m = re.match(r"^---[ \t]*\n(.*?)\n---[ \t]*\n", txt, re.S)
    if not m:
        return "skip_no_fm"
    fm = m.group(1)
    try:
        pkg = EventPackage.from_markdown(txt, filepath=fp)
    except Exception as e:
        return f"err_parse:{e}"
    anchors = pkg.anchors or []
    if not anchors:
        return "skip_empty"

    block = pkg._fmt_anchors_block()  # list of lines, 首项为 'anchors:'

    # 在 fm 行内定位 anchors 条目 [start, end)
    fmlines = fm.split("\n")
    start = None
    for i, ln in enumerate(fmlines):
        if re.match(r"^anchors:", ln):
            start = i
            break
    if start is None:
        return "skip_no_anchors_field"
    end = len(fmlines)
    for j in range(start + 1, len(fmlines)):
        if fmlines[j] and not fmlines[j][0].isspace():  # 下一个 indent-0 字段
            end = j
            break

    new_fmlines = fmlines[:start] + block + fmlines[end:]
    new_fm = "\n".join(new_fmlines)
    new_txt = txt[: m.start(1)] + new_fm + txt[m.end(1) :]

    # round-trip 验证
    try:
        pkg2 = EventPackage.from_markdown(new_txt, filepath=fp)
    except Exception as e:
        return f"err_reparse:{e}"
    if pkg2.anchors != anchors:
        return "err_roundtrip_mismatch"
    for a, b in zip(anchors, pkg2.anchors or []):
        if (a.get("keywords") or []) != (b.get("keywords") or []):
            return "err_kw_mismatch"

    if new_txt == txt:
        return f"skip_unchanged:{len(anchors)}"
    open(fp, "w", encoding="utf-8").write(new_txt)
    return f"converted:{len(anchors)}"


def main():
    n_conv = n_skip = n_err = 0
    for root, _, files in os.walk(MEM):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(root, fn)
            r = convert_file(fp)
            if r.startswith("converted"):
                n_conv += 1
                if n_conv <= 6:
                    print("  CONV", fp, r)
            elif r.startswith("skip"):
                n_skip += 1
            else:
                n_err += 1
                print("  ERR ", fp, r)
    print(f"\nDONE converted={n_conv} skip={n_skip} err={n_err}")


if __name__ == "__main__":
    main()
