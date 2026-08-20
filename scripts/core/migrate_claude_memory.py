# -*- coding: utf-8 -*-
"""migrate_claude_memory —— (claude-only 适配器） 把 Claude Code 的 AutoMemory
（~/.claude/projects/<hash>/memory/）按内容归类导入 HMA 规范命名空间。

R49 设计翻转：废弃 external/ 隔离，改为「拆碎、按内容归类」进
User / Project / Other 等命名空间（由 --namespace 指定，AI 判定内容归属）。
每条导入事件携带 tags=[src:claude, imported] + 正文末 `> 来源:` 溯源行，
稳定 eid 保证重跑幂等。

设计对齐 CEMA / HMA 不变量：
- 全量原文灌入（忠实，不增删、不摘要改写）——Claude 内存本就是干净 markdown。
- 每个源 .md 文件 = 一个 HMA 事件（忠实映射，不强行重排）。
- 统一前台 db 自动接住（package_id = <namespace>/<client> 路径推出）。
- 时间 = WHERE 过滤键（写进 created/updated），非排序权重。

用法（cwd = 仓库根）：
  python scripts/core/migrate_claude_memory.py \
      [--projects-dir ~/.claude/projects] \
      [--root memory] \
      [--namespace Other] \
      [--only memory,debugging]   # 只导指定文件名 stem，默认全导
"""
import os
import sys
import glob
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from hma.import_common import write_imported


def discover(projects_dir):
    """每个 <hash>/memory/ 是一个 Claude 项目的 AutoMemory 根。"""
    return sorted(glob.glob(os.path.join(projects_dir, "*", "memory")))


def _stem(fn):
    return os.path.splitext(os.path.basename(fn))[0].lower()


def migrate(projects_dir, memory_root, namespace, only=None):
    roots = discover(projects_dir)
    if not roots:
        print("未找到 Claude Code AutoMemory（%s/*/memory）" % projects_dir)
        return

    total = 0
    today = datetime.date.today().isoformat()
    for mem_dir in roots:
        hash_dir = os.path.basename(os.path.dirname(mem_dir))
        client = "claude-" + hash_dir[:12]
        # 源文件：memory/ 下全部 .md + 同级 CLAUDE.md（项目级指令）
        srcs = sorted(glob.glob(os.path.join(mem_dir, "*.md")))
        claude_md = os.path.join(os.path.dirname(mem_dir), "CLAUDE.md")
        if os.path.exists(claude_md):
            srcs.append(claude_md)
        if only:
            srcs = [s for s in srcs if _stem(s) in only]
        if not srcs:
            continue

        for f in srcs:
            stem = _stem(f)
            eid = "claude" if stem == "claude" else stem  # MEMORY.md → memory
            with open(f, encoding="utf-8") as fh:
                body = fh.read().strip()
            if not body:
                continue
            title = "Claude记忆·" + os.path.basename(f)
            write_imported(memory_root, namespace, client, eid, title,
                           body, f, created=today)
            total += 1
            print("  + %s/%s/%s  (%s)" % (namespace, client, eid, os.path.basename(f)))
        print("已迁移 Claude 项目 %s → 包 %s/%s" % (hash_dir[:12], namespace, client))
    print("总事件数：%d" % total)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Claude Code AutoMemory → HMA 命名空间（R49 翻转：废弃 external/）")
    ap.add_argument("--projects-dir",
                    default=os.path.expanduser("~/.claude/projects"),
                    help="Claude Code projects 目录（默认 ~/.claude/projects）")
    ap.add_argument("--root", default="memory",
                    help="HMA 记忆根（默认 memory）")
    ap.add_argument("--namespace", default="其他",
                    help="落入的规范命名空间（User/项目/Other，默认 Other；由 AI 判定内容归类）")
    ap.add_argument("--only",
                    help="只导这些文件名 stem（逗号分隔，如 memory,debugging），默认全导")
    a = ap.parse_args()
    only = set(x.strip().lower() for x in (a.only or "").split(",") if x.strip()) or None
    migrate(a.projects_dir, a.root, a.namespace, only)
