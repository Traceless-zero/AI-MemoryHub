# -*- coding: utf-8 -*-
"""memory_append_section —— 往已有 .md 记忆包「按章节标题追加/新建章节」的确定性 sink。

这是 AIMH 写回哲学（CEMA）里**长期缺的那块确定性工具**：
  - daylog_append.py  只管「事件流」(memory/日志/daylog-*.md 的 ## 流水)
  - 本脚本管「话题/事件包」的章节级增补 —— 对应「什么话题事件就去那个 md 增加章节或修改内容」

职责切分（AI 零路由，AI 只决策、脚本只写盘）：
  - AI 负责：决定落到哪个包(package_id)、哪个章节(section)、写什么(body)
  - 脚本负责：定位 .md、按章节标题定位插入点、机械写盘、刷新 pkage_updated
  - CEMA 铁律：默认**追加不覆盖**；绝不静默改写已有章节内容（矛盾/更新由理解层判定，
    写入时不覆盖旧决定）。需要整节替换须显式 --replace 且会告警。

落点哲学（来自 aimh-ingest SKILL.md）：
  - 内容命中某已有包的语义域 → 增补进该包（增加/修改章节），不新建
  - 跨模块新主题 → 由调用方新建包（见下方 Memory.write 或 demo 的 new_package）
  - daylog 仅装闲话+大事件简介+关联，结构化跟踪进正经包、不进 daylog

用法：
  python memory_append_section.py --pkg "项目/AIMH/检索架构" --section "## 待办" --body "..."
  python memory_append_section.py --pkg "项目/AIMH/检索架构" --section "## 已完成"
      --body-file /tmp/done.md
  # 整节替换（需显式，会告警）：
  python memory_append_section.py --pkg "..." --section "## 设计" --body "..." --replace
"""
import argparse
import io
import os
import re
import sys

DERIVED_HINT = "memory"


def repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        if os.path.isdir(os.path.join(cand, DERIVED_HINT)):
            return cand
    if os.path.isdir(os.path.join(os.getcwd(), DERIVED_HINT)):
        return os.getcwd()
    return here


def _resolve_path(root, pkg, path):
    if pkg:
        return os.path.join(root, DERIVED_HINT, pkg + ".md")
    if path:
        p = path if path.endswith(".md") else path + ".md"
        return os.path.join(root, DERIVED_HINT, p)
    return None


def _bump_updated(text, today):
    if re.search(r"^pkage_updated:.*$", text, flags=re.M):
        return re.sub(r"^pkage_updated:.*$", "pkage_updated: %s" % today, text, flags=re.M)
    return text


def append_section(md_path, section, body, replace=False):
    """在 md_path 里：section 标题已存在 -> 该节末尾追加 body（默认）；不存在 -> 文件末尾新建节。
    返回 ('appended'|'created'|'replaced', 实际写入的节标题)。"""
    if not os.path.exists(md_path):
        raise FileNotFoundError("包不存在，无法增补：%s（请先新建包）" % md_path)
    with io.open(md_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    # FM 块（---...---）不参与章节定位
    fm_end = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_end = i + 1
                break

    body_lines = [ln for ln in (body or "").strip("\n").splitlines() if ln.strip()]
    block = ["", section.strip()] + body_lines + [""]

    # 找 section 节位置
    start = None
    for i in range(fm_end, len(lines)):
        if lines[i].strip() == section.strip():
            start = i
            break

    if start is not None:
        # 该节已存在：定位节末尾（下一同级或更高级 ## 之前，或 EOF）
        end = len(lines)
        sec_level = len(section) - len(section.lstrip("#"))
        for j in range(start + 1, len(lines)):
            m = re.match(r"^(#{1,6})\s", lines[j])
            if m and len(m.group(1)) <= sec_level:
                end = j
                break
        if replace:
            new_lines = lines[:start + 1] + body_lines + [""] + lines[end:]
            action = "replaced"
        else:
            new_lines = lines[:end] + block + lines[end:]
            action = "appended"
    else:
        # 新建节：追加到文件末尾（普通包无 ## 流水 固定节；daylog 不走此脚本）
        new_lines = lines + block
        action = "created"

    text = "\n".join(new_lines).rstrip("\n") + "\n"
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _bump_updated(text, __import__("datetime").date.today().isoformat())
    tmp = md_path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, md_path)
    return action, section.strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description="往已有 .md 记忆包按章节标题追加/新建章节")
    ap.add_argument("--pkg", default=None, help="package_id，如 项目/AIMH/检索架构")
    ap.add_argument("--path", default=None, help="相对 memory/ 的 .md 路径（与 --pkg 二选一）")
    ap.add_argument("--section", required=True, help="章节标题，如 '## 待办' / '### 进度'")
    ap.add_argument("--body", default=None, help="章节内容（缺省读 --body-file 或 stdin）")
    ap.add_argument("--body-file", default=None)
    ap.add_argument("--replace", action="store_true", help="整节替换（默认追加；替换会告警）")
    args = ap.parse_args(argv)

    root = repo_root()
    md_path = _resolve_path(root, args.pkg, args.path)
    if not md_path:
        print("[x] 须提供 --pkg 或 --path")
        return 1
    if not os.path.exists(md_path):
        print("[x] 包不存在：%s（请先新建包，本脚本只增补已有包）" % md_path)
        return 1

    if args.body is not None:
        body = args.body
    elif args.body_file:
        with io.open(args.body_file, "r", encoding="utf-8") as f:
            body = f.read()
    else:
        body = sys.stdin.read()

    if args.replace:
        print("[!] 整节替换模式：将覆盖 '%s' 现有内容（CEMA 默认不覆盖，谨慎）" % args.section)
    action, sec = append_section(md_path, args.section, body, replace=args.replace)
    rel = os.path.relpath(md_path, root).replace("\\", "/")
    print("[+] %s -> %s 节 '%s'（pkage_updated 已刷新）" % (rel, action, sec))
    print("[!] 落盘后请重建索引：python scripts/core/rebuild_index.py --no-gui")
    return 0


if __name__ == "__main__":
    sys.exit(main())
