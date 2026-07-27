# -*- coding: utf-8 -*-
"""archive_paper.py —— hma-ingest（文章/资料分支）技能的确定性落库原语（落库归脚本）。

两个模式：
  orig   把源 .md 逐字拷为 HMA 的 `<id>` 原文包（守"长文不压缩"，
         不进 LLM 转录，保证 verbatim）。
  review 读一个"理解综述 .md"（Agent 生成的正文，无 front-matter），
         按给定元数据写进 HMA 的 `<id>` 综述包。

用法：
  python scripts/archive_paper.py orig <src.md> <memory_root> <pkg_rel> <id> <title> <summary> <tags_csv> [<aliases_csv>]
  python scripts/archive_paper.py review <review.md> <memory_root> <pkg_rel> <id> <title> <summary> <tags_csv> [<aliases_csv>]

例：
  python scripts/archive_paper.py orig "E:/BaiduNetdiskDownload/尼采.md" memory "Other/哲学/尼采" \
      nietzsche-orig "弗里德里希·尼采：哲学思想综述与理解" \
      "尼采思想综述：上帝之死/权力意志/超人/永恒轮回（用户个人记录）" "paper,哲学,尼采"
  python scripts/archive_paper.py review /tmp/nietzsche-review.md memory "Other/哲学/尼采" \
      nietzsche-review "尼采哲学思想 · 理解综述" "尼采：道德谱系学锤子——拆穿价值人造性、把追问权交还个体" \
      "paper,review,哲学,尼采"
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
from hma.hma_core import Memory  # noqa: E402


def _meta(argv):
    src, mroot, pkg_rel, eid, title, summary = argv[0:6]
    tags = argv[6].split(",") if len(argv) > 6 and argv[6] else []
    aliases = argv[7].split(",") if len(argv) > 7 and argv[7] else []
    return src, mroot, pkg_rel, eid, title, summary, tags, aliases


def main():
    mode = sys.argv[1]
    meta = _meta(sys.argv[2:])
    src, mroot, pkg_rel, eid, title, summary, tags, aliases = meta
    root = os.path.join(mroot, *pkg_rel.split("/"))
    m = Memory(root)
    with open(src, "r", encoding="utf-8") as f:
        body = f.read().strip()
    m.write(id=eid, title=title, summary=summary,
             tags=tags, aliases=aliases, body=body, trigger="hma-ingest")
    m.close()
    print("ok %s -> %s" % (mode, os.path.join(root, eid + ".md")))


if __name__ == "__main__":
    main()
