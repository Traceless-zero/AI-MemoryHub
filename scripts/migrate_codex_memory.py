# -*- coding: utf-8 -*-
"""migrate_codex_memory —— (codex-only 适配器） 把 Codex CLI 的 Memories（~/.codex/memories/）
按内容归类导入 HMA 规范命名空间（R49 翻转：废弃 external/）。

每条导入事件携带 tags=[src:codex, imported] + 正文末 `> 来源:` 溯源行，
稳定 eid 保证重跑幂等。

Codex 记忆模型（两层）：
- Layer1 AGENTS.md：静态指令（类 CLAUDE.md），手动维护
  → 本适配器【不导】（那是规则，不是记忆）。
- Layer2 Memories：自动生成层，落本地文件 ~/<codex_dir>/memories/：
    MEMORY.md            主注入点（合并后的原始抽取）
    rollout_summaries/  每次 rollout 的摘要（2026-04-15-refactor-auth.md …）
    skills/              习得的过程性记忆
    memories_extensions/ 插件贡献的记忆
  这就是 Codex 的「长期记忆」，与 Claude AutoMemory / Gemini GEMINI.md 同构。

设计对齐 CEMA / HMA 不变量（同构于 migrate_claude_memory.py）：
- 全量原文灌入（忠实，不增删、不摘要改写）。
- 每个源 .md = 一个 HMA 事件（忠实映射；子目录用前缀区分，不破坏包级 1:1）。
- 统一前台 db 自动接住（package_id = <namespace>/<client> 路径推出）。
- 时间 = WHERE 过滤键（写进 created/updated），非排序权重。

用法（cwd = 仓库根）：
  python scripts/migrate_codex_memory.py \
      [--codex-dir ~/.codex] \
      [--root memory] \
      [--namespace Other] \
      [--only memory,2026-04-15-refactor-auth]   # 只导指定文件名 stem
"""
import os
import sys
import glob
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hma.import_common import write_imported


# 子目录 → HMA 事件 id 前缀（保持可追溯，不破坏包级 1:1）
_SUBDIR = {
    "rollout_summaries": "rollout",
    "skills": "skill",
    "memories_extensions": "ext",
}


def discover(codex_dir):
    """memories/ 根级 .md + 已知子目录的 .md。"""
    mem_root = os.path.join(codex_dir, "memories")
    if not os.path.isdir(mem_root):
        return []
    out = []
    out += sorted(glob.glob(os.path.join(mem_root, "*.md")))      # MEMORY.md 等
    for d in _SUBDIR:                                             # 子目录
        out += sorted(glob.glob(os.path.join(mem_root, d, "*.md")))
    return out


def _stem(fn):
    return os.path.splitext(os.path.basename(fn))[0].lower()


def _eid(fn, mem_root):
    rel = os.path.relpath(fn, mem_root)
    parts = rel.split(os.sep)
    stem = _stem(fn)
    if len(parts) == 1:
        # 根级：MEMORY.md → 事件 id=memory
        return "memory" if stem in ("memory", "memories") else stem
    # 子目录：<prefix>-<stem>
    sub = parts[0]
    prefix = _SUBDIR.get(sub, sub)
    return "%s-%s" % (prefix, stem)


def migrate(codex_dir, memory_root, namespace, only=None):
    files = discover(codex_dir)
    if not files:
        print("未找到 Codex Memories（%s/memories/）" % codex_dir)
        return
    if only:
        files = [f for f in files if _stem(f) in only]
    if not files:
        return

    total = 0
    client = "codex"
    mem_root = os.path.join(codex_dir, "memories")
    today = datetime.date.today().isoformat()
    for f in files:
        eid = _eid(f, mem_root)
        with open(f, encoding="utf-8") as fh:
            body = fh.read().strip()
        if not body:
            continue
        title = "Codex记忆·" + os.path.basename(f)
        write_imported(memory_root, namespace, client, eid, title,
                       body, f, created=today)
        total += 1
        print("  + %s/%s/%s" % (namespace, client, eid))
    print("已迁移 Codex Memories → 包 %s/%s（%d 事件）" % (namespace, client, total))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Codex CLI Memories → HMA 命名空间（R49 翻转：废弃 external/）")
    ap.add_argument("--codex-dir",
                    default=os.path.expanduser("~/.codex"),
                    help="Codex 主目录（默认 ~/.codex，可用 CODEX_HOME 改）")
    ap.add_argument("--root", default="memory",
                    help="HMA 记忆根（默认 memory）")
    ap.add_argument("--namespace", default="其他",
                    help="落入的规范命名空间（User/项目/Other，默认 Other；由 AI 判定内容归类）")
    ap.add_argument("--only",
                    help="只导这些文件名 stem（逗号分隔，默认全导）")
    a = ap.parse_args()
    only = set(x.strip().lower() for x in (a.only or "").split(",")
               if x.strip()) or None
    migrate(a.codex_dir, a.root, a.namespace, only)
