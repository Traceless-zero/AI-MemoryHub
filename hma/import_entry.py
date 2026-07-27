# -*- coding: utf-8 -*-
"""import_entry —— 细粒度「一条客户端记忆 → HMA 规范命名空间」落库 CLI。

供 memory-import 技能在「拆碎原客户端记忆、按内容归类」时使用：
AI 读取客户端原生记忆、切成逻辑条目、判定每条归属的命名空间
（User / Project / Other）、给定稳定 eid，再逐条调用本 CLI 确定性落库。

理解归 AI，落库归本 CLI（纯确定性写，详见 hma/import_common.py）。

用法（cwd = 仓库根，脚本路径形式最稳）：
  python hma/import_entry.py \
      --root .memory --namespace User --client claude \
      --id claude-pref-py --title "用户偏好 Python" \
      --source "~/.claude/projects/<hash>/memory/preferences.md" \
      --body-file /tmp/chunk.md [--created 2026-07-25] [--tags "py,pref"]

（也可 cwd = hma/ 目录时 `python -m hma.import_entry ...`）
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hma.import_common import write_imported


def main():
    ap = argparse.ArgumentParser(description="客户端记忆单条 → HMA 命名空间")
    ap.add_argument("--root", default=".memory",
                    help="HMA 记忆根（默认 .memory）")
    ap.add_argument("--namespace", required=True,
                    help="规范命名空间：User / Project / Other …")
    ap.add_argument("--client", required=True,
                    help="源客户端标识（claude/gemini/codex/wb）")
    ap.add_argument("--id", required=True,
                    help="稳定事件 id（幂等覆盖键）")
    ap.add_argument("--title", required=True, help="事件标题")
    ap.add_argument("--source", required=True,
                    help="溯源引用（原记忆文件位置）")
    ap.add_argument("--body-file", required=True,
                    help="正文文件路径（原文）")
    ap.add_argument("--created", help="创建日期（WHERE 过滤键）")
    ap.add_argument("--tags", help="逗号分隔的额外标签")
    a = ap.parse_args()
    with open(a.body_file, encoding="utf-8") as fh:
        body = fh.read().strip()
    if not body:
        print("跳过：空正文（%s）" % a.body_file)
        return
    extra = [t.strip() for t in (a.tags or "").split(",") if t.strip()]
    root = write_imported(a.root, a.namespace, a.client, a.id,
                          a.title, body, a.source, a.created, extra)
    print("已导入 → %s/%s/%s (id=%s)" % (a.root, a.namespace, a.client, a.id))


if __name__ == "__main__":
    main()
