# -*- coding: utf-8 -*-
"""注释主张对账审计（comment-pin audit）——零依赖、只读。

职责：扫源码注释里引用的「可钉主张」——用例编号（T01/T14、P08）、测试文件名
（regress_*/bench_*）、历史事故编号（G#-Q#、defect X、Edit N）——到
scripts/tests/ 找钉住它的断言或文件；找不到钉子的列出来（漂移候选）。

立场（对应工程红线与自检纪律 §3⑦ 提案）：注释是可证伪主张，用例才是契约。
本脚本只做机械对账；语义级漂移（注释说 A 代码做 B 且无用例钉）仍需按红线
⑦ 由 AI/人跑真实复现审查。

用法：
  python audit_comment_pins.py --repo <仓库根>
"""

import argparse
import io
import os
import re
import sys

CASE_ID = re.compile(r"\b(?:T|P)\d{2}\b")
GQ_ID = re.compile(r"\bG\d+-Q\d+\b")
DEFECT = re.compile(r"\bdefect\s*[A-Z]\b", re.I)
EDIT_N = re.compile(r"\bEdit\s*\d+\b", re.I)
TEST_FILE = re.compile(r"\b((?:regress|bench)_[a-z0-9_]+)\b")
EXCLUDE_DIRS = {".git", "__pycache__", "memory", "to_delete", ".workbuddy",
                ".zcode", "node_modules", "vendor", "ff_workspace", "json"}


def collect_pins(tests_dir):
    """回归集里真实存在的钉子：用例 id 集合 + 测试文件名集合。"""
    case_ids, test_files = set(), set()
    if not os.path.isdir(tests_dir):
        return case_ids, test_files
    for fn in sorted(os.listdir(tests_dir)):
        if not fn.endswith(".py"):
            continue
        test_files.add(fn[:-3])
        try:
            with io.open(os.path.join(tests_dir, fn), encoding="utf-8",
                         errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        case_ids |= set(re.findall(r'["\']((?:T|P)\d{2})["\']', text))
        case_ids |= set(re.findall(r'["\'](G\d+-Q\d+)["\']', text))
    return case_ids, test_files


def iter_comments(path):
    """逐行产出 (行号, 注释文本)。只认 # 注释；docstring 主张由红线⑦人工审。"""
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            _, _, comment = line.partition("#")
            if comment.strip():
                yield i, comment


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="仓库根")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    tests_dir = os.path.join(repo, "scripts", "tests")
    case_ids, test_files = collect_pins(tests_dir)

    n_files = 0
    rows = []  # (rel, line, kind, token, status)
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            n_files += 1
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, repo).replace("\\", "/")
            for ln, comment in iter_comments(fp):
                for mt in CASE_ID.finditer(comment):
                    tok = mt.group(0)
                    rows.append((rel, ln, "用例编号", tok,
                                 "pinned" if tok in case_ids else "UNPINNED"))
                for mt in TEST_FILE.finditer(comment):
                    tok = mt.group(1)
                    ok = tok in test_files
                    rows.append((rel, ln, "测试文件", tok,
                                 "pinned" if ok else "UNPINNED"))
                for mt in GQ_ID.finditer(comment):
                    rows.append((rel, ln, "事故编号", mt.group(0), "人工核"))
                for mt in DEFECT.finditer(comment):
                    rows.append((rel, ln, "事故编号", mt.group(0), "人工核"))
                for mt in EDIT_N.finditer(comment):
                    rows.append((rel, ln, "事故编号", mt.group(0), "人工核"))

    pinned = [r for r in rows if r[4] == "pinned"]
    unpinned = [r for r in rows if r[4] == "UNPINNED"]
    manual = [r for r in rows if r[4] == "人工核"]
    print("== 注释主张对账审计 ==")
    print("扫描 .py 文件 %d 个；回归集钉子：用例 %d 个 / 测试文件 %d 个"
          % (n_files, len(case_ids), len(test_files)))
    print("引用统计：pinned=%d  UNPINNED=%d  人工核=%d"
          % (len(pinned), len(unpinned), len(manual)))
    if unpinned:
        print("\n-- UNPINNED 明细（注释引用了不存在/已改名的用例或测试 → 漂移候选）--")
        for rel, ln, kind, tok, _ in unpinned:
            print("  %s:%d  [%s] %s" % (rel, ln, kind, tok))
    print("\n-- 人工核明细（事故编号类，钉子在设计日志/回归注释，机械不可查）--")
    seen = set()
    for rel, ln, kind, tok, _ in manual:
        if (kind, tok) in seen:
            continue
        seen.add((kind, tok))
        print("  %s %s  ← 首见 %s:%d" % (kind, tok, rel, ln))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
