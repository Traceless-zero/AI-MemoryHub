# -*- coding: utf-8 -*-
"""migrate_gemini_memory —— (gemini-only 适配器） 把 Gemini CLI 的持久记忆
（~/.gemini/GEMINI.md，含 save_memory 工具写入的「## Gemini Added Memories」）
按内容归类导入 HMA 规范命名空间（R49 翻转：废弃 external/）。

每条导入事件携带 tags=[src:gemini, imported] + 正文末 `> 来源:` 溯源行，
稳定 eid 保证重跑幂等。

设计对齐 CEMA / HMA 不变量（同构于 migrate_claude_memory.py）：
- 全量原文灌入（忠实，不增删、不摘要改写）。
- 每个源 .md = 一个 HMA 事件（忠实映射，不强行重排）。
- 统一前台 db 自动接住（package_id = <namespace>/<client> 路径推出）。
- 时间 = WHERE 过滤键（写进 created/updated），非排序权重。

Gemini CLI 记忆模型：
- 全局记忆文件默认 ~/.gemini/GEMINI.md；文件名可在 settings 中改。
- save_memory(fact) 把事实追加到该文件的「## Gemini Added Memories」段；
  这是 Gemini 的「长期记忆」层（类比 Claude 的 AutoMemory / Codex 的 Memories）。
- 另有项目级 ./GEMINI.md（递归向上/向下搜索），那是「项目指令」而非记忆，
  本适配器默认只导全局记忆文件（长期记忆），避免把项目规则当记忆污染。

用法（cwd = 仓库根）：
  python scripts/migrate_gemini_memory.py \
      [--gemini-dir ~/.gemini] \
      [--memory-file GEMINI.md] \
      [--root memory] \
      [--namespace Other] \
      [--only memory]   # 只导指定文件名 stem，默认全导
"""
import os
import sys
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hma.import_common import write_imported


def discover(gemini_dir, memory_file):
    """全局记忆文件：~/.gemini/<memory_file>（默认 GEMINI.md）。"""
    p = os.path.join(gemini_dir, memory_file)
    return [p] if os.path.exists(p) else []


def _stem(fn):
    return os.path.splitext(os.path.basename(fn))[0].lower()


def migrate(gemini_dir, memory_file, memory_root, namespace, only=None):
    files = discover(gemini_dir, memory_file)
    if not files:
        print("未找到 Gemini CLI 记忆文件（%s/%s）"
              % (gemini_dir, memory_file))
        return
    if only:
        files = [f for f in files if _stem(f) in only]
    if not files:
        return

    total = 0
    client = "gemini"
    today = datetime.date.today().isoformat()
    for f in files:
        stem = _stem(f)
        # GEMINI.md → 事件 id=memory；其余文件名 stem 直用
        eid = "memory" if stem == "gemini" else stem
        with open(f, encoding="utf-8") as fh:
            body = fh.read().strip()
        if not body:
            continue
        title = "Gemini记忆·" + os.path.basename(f)
        write_imported(memory_root, namespace, client, eid, title,
                       body, f, created=today)
        total += 1
        print("  + %s/%s/%s" % (namespace, client, eid))
    print("已迁移 Gemini CLI 记忆 → 包 %s/%s（%d 事件）" % (namespace, client, total))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Gemini CLI 记忆 → HMA 命名空间（R49 翻转：废弃 external/）")
    ap.add_argument("--gemini-dir",
                    default=os.path.expanduser("~/.gemini"),
                    help="Gemini CLI 主目录（默认 ~/.gemini）")
    ap.add_argument("--memory-file", default="GEMINI.md",
                    help="记忆文件名（默认 GEMINI.md，可在 settings 中改名）")
    ap.add_argument("--root", default="memory",
                    help="HMA 记忆根（默认 memory）")
    ap.add_argument("--namespace", default="其他",
                    help="落入的规范命名空间（User/项目/Other，默认 Other；由 AI 判定内容归类）")
    ap.add_argument("--only",
                    help="只导这些文件名 stem（逗号分隔，如 memory），默认全导")
    a = ap.parse_args()
    only = set(x.strip().lower() for x in (a.only or "").split(",")
               if x.strip()) or None
    migrate(a.gemini_dir, amemory_file, a.root, a.namespace, only)
