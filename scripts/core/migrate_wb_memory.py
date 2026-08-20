# -*- coding: utf-8 -*-
"""migrate_wb_memory —— (wb-only 适配器） 把 WB 自带工作日志（项目级 .workbuddy/memory/2026-*.md）
全量迁移进 HMA 的 hma-design-journal 包 —— 给 WB 的记忆装上 CEMA 前台索引
（可检索、可链接、按需取正文）。

设计对齐 CEMA / HMA 不变量：
- 全量原文灌入（忠实，不增删、不摘要改写）。
- 确定性重排标题层级：H1 日期跳过；### 第N轮 / Round N 提升为 ##；
  非轮次 ## 话题 留 ##、其 ### 子节留 ###。
- 时间是 WHERE 过滤键（写进每段日期后缀 + > 来源），非排序权重。
- 归入既有包 hma-design-journal（事件 dev），不另立包。

用法（cwd = 仓库根）：
  python scripts/core/migrate_wb_memory.py \
      --wb-dir "/项目/.workbuddy/memory" \
      --root memory/项目/hma-design-journal --id dev \
      --title "项目开发日志"
"""
import os
import sys
import glob
import re
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from hma.import_common import _lead_line, write_imported


def _chinese_to_int(s):
    """中文数字 → 阿拉伯数字（支持"十"到"九十九"）。"""
    cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    s = s.strip()
    if s in cn:
        return cn[s]
    if s.startswith("十") and len(s) == 2:
        return 10 + cn.get(s[1], 0)
    if s.endswith("十") and len(s) == 2:
        return cn.get(s[0], 0) * 10
    if len(s) == 2:
        return cn.get(s[0], 0) * 10 + cn.get(s[1], 0)
    return int(s) if s.isdigit() else 0


def _round_key(line):
    """从 '第X轮' / 'Round N' 行提取排序键（数字越大越靠前）。"""
    m = re.match(r"^###\s+第([一二三四五六七八九十\d]+)轮", line)
    if m:
        return _chinese_to_int(m.group(1))
    m = re.match(r"^###\s+[Rr]ound\s+(\d+)", line)
    if m:
        return int(m.group(1))
    return 0


def _is_round_heading(line):
    """"### 第N轮" 或 "### Round N"。"""
    return bool(re.match(r"^###\s+(第[一二三四五六七八九十\d]+轮|[Rr]ound\s+\d+)", line))


def _rearrange(body, date_str):
    """确定性重排：提取 H2/H3 结构 → 轮次提升、日期缀入、来源标注。"""
    lines = body.splitlines()
    out = []
    # 跳过 H1 日期行
    start = 0
    for i, ln in enumerate(lines):
        if ln.startswith("# ") and not ln.startswith("## "):
            start = i + 1
            break

    buf = []
    current_h2 = None
    current_h2_is_round = False

    def flush():
        nonlocal buf, current_h2, current_h2_is_round
        if not buf:
            return
        # 轮次 → 提升为 ##；非轮次话题 → 保留原级
        if current_h2:
            if current_h2_is_round:
                out.append("## %s" % current_h2)
            else:
                out.append("## %s" % current_h2)
        out.extend(buf)
        out.append("")
        buf = []
        current_h2 = None
        current_h2_is_round = False

    for ln in lines[start:]:
        if ln.startswith("### ") and _is_round_heading(ln):
            flush()
            title = ln[4:].strip()
            current_h2 = "%s (%s)" % (title, date_str)
            current_h2_is_round = True
        elif ln.startswith("## "):
            flush()
            current_h2 = ln[3:].strip()
            current_h2_is_round = False
        elif ln.startswith("# ") and not ln.startswith("## "):
            flush()
        else:
            buf.append(ln)
    flush()

    # 追加来源
    out.append("> 来源: WorkBuddy 原生记忆 @ .workbuddy/memory/%s.md" % date_str)
    return "\n".join(out)


def migrate(wb_dir, memory_root, pkg_id, title):
    """读 2026-*.md → 确定性重排 → 写 HMA dev 事件。"""
    pattern = os.path.join(wb_dir, "2026-*-*.md")
    files = sorted(glob.glob(pattern))
    if not files:
        print("未找到 WB 工作日志（%s）" % pattern)
        return

    # 排除 MEMORY/README/proj-*
    files = [f for f in files
             if os.path.basename(f).startswith("2026-")]

    parts = []
    total = 0
    for f in files:
        fn = os.path.basename(f)
        date_str = fn.replace(".md", "")
        with open(f, encoding="utf-8") as fh:
            raw = fh.read()
        rearranged = _rearrange(raw, date_str)
        if rearranged.strip():
            parts.append(rearranged)
            total += 1
            print("  + %s" % fn)

    if not parts:
        print("无有效内容")
        return

    full_body = "\n\n".join(parts)
    n_rounds = len(re.findall(r"^##\s+第[一二三四五六七八九十\d]+轮", full_body, re.M))
    n_rounds += len(re.findall(r"^##\s+[Rr]ound\s+\d+", full_body, re.M))
    summary = _lead_line(full_body) or ("%s：WB 工作日志全量迁移，共 %d 个轮次章节" % (title, n_rounds))

    write_imported(memory_root, "项目/hma-design-journal", "wb", pkg_id, title,
                   full_body, wb_dir,
                   extra_tags=["wb-derived", "project-log"])
    print("已迁移 %d 天 → 事件 %s（%d 轮次）" % (total, pkg_id, n_rounds))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="WB 工作日志 → HMA hma-design-journal 包（确定性重排，零 LLM 依赖）")
    ap.add_argument("--wb-dir",
                    help="WB 项目级 memory 目录（如 .workbuddy/memory）")
    ap.add_argument("--root", default="memory/项目/hma-design-journal",
                    help="HMA 目标包根目录（默认 memory/项目/hma-design-journal）")
    ap.add_argument("--id", default="dev",
                    help="事件 id（默认 dev）")
    ap.add_argument("--title", default="项目开发日志",
                    help="事件标题（默认 项目开发日志）")
    a = ap.parse_args()
    if not a.wb_dir:
        ap.error("请指定 --wb-dir（WB 项目级 memory 目录）")
    migrate(a.wb_dir, a.root, a.id, a.title)
