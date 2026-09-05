# -*- coding: utf-8 -*-
"""AIMH 召回卡读卡器（ZCode SessionStart hook，fail-open）
========================================================

职责边界（2026-09-05 设计裁决）：hook 只做「呈现」，不做「检索」——
把 skills/aimh-recall/references/recall_card.md 注入会话上下文即结束，
构查（关键词提炼）与相关性判断全部留给驾驶模型经 MCP 工具完成。
本脚本不跑任何查询、不断言任何相关性、不写任何文件。

输出契约（依 diagnosing-hooks 口径）：
- stdout 为严格 JSON。默认输出 {"additionalContext": <卡文本>}；
  若事件校验不通过（log 里出现 hook failed），改用 --format wrapped
  输出 hookSpecificOutput 包裹版。
- JSON 一律 ensure_ascii（纯 ASCII 传输），彻底规避 Windows 管道 cp936 转码。
- 任何异常 / 卡缺失 / 卡为空 → 静默 exit 0（fail-open，绝不阻塞会话）。
- exit 2 保留给「故意阻断」，本脚本永不使用。

工作区护栏（用户级 hook 对全工作区生效，2026-09-05 实证 workspace 级
hooks 有信任门 config.project_hooks.pending_trust 会静默拦置，故迁用户级）：
- 以 --project-dir ${ZCODE_PROJECT_DIR} 传入当前工作区，仅当落在本仓库内
  才注入；其他工作区静默 exit 0。
- 模板变量未展开（传入门面话 "${...}" 字面量）→ 视为无法判定 → 宁静默不误注。

用法：
  python aimh_recall_card_hook.py                  # hook 模式（JSON 注入）
  python aimh_recall_card_hook.py --print          # 人读模式（原样打印卡片）
  python aimh_recall_card_hook.py --card <path>    # 指定卡路径（测试/覆盖）
  python aimh_recall_card_hook.py --format wrapped # hookSpecificOutput 包裹版
  python aimh_recall_card_hook.py --project-dir <dir>  # 工作区护栏判据
"""

import io
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CARD = REPO_ROOT / "skills" / "aimh-recall" / "references" / "recall_card.md"


def _in_aimh_workspace(project_dir):
    """project_dir 落在本仓库内才允许注入；空值=无法判定，放行（兼容手工运行）。"""
    if not project_dir:
        return True
    p = os.path.normcase(os.path.normpath(project_dir))
    if p.startswith("${"):  # 模板变量未被展开 → 宁静默不误注
        return False
    repo = os.path.normcase(os.path.normpath(str(REPO_ROOT)))
    return p == repo or p.startswith(repo + os.sep)


def _load_card(path):
    text = io.open(path, "r", encoding="utf-8").read().strip()
    return text or None


def _emit_json(text, wrapped):
    if wrapped:
        payload = {"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }}
    else:
        payload = {"additionalContext": text}
    # ensure_ascii=True：输出纯 ASCII，任何管道编码下都不转码失真
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))
    sys.stdout.write("\n")


def main(argv):
    try:
        card_path = DEFAULT_CARD
        project_dir = None
        wrapped = False
        human = False
        i = 0
        while i < len(argv):
            if argv[i] == "--card" and i + 1 < len(argv):
                card_path = Path(argv[i + 1])
                i += 2
            elif argv[i] == "--project-dir" and i + 1 < len(argv):
                project_dir = argv[i + 1]
                i += 2
            elif argv[i] == "--format" and i + 1 < len(argv):
                wrapped = argv[i + 1] == "wrapped"
                i += 2
            elif argv[i] == "--print":
                human = True
                i += 1
            else:
                i += 1

        if not _in_aimh_workspace(project_dir):
            return 0  # 其他工作区 → 静默，卡片只属于 AIMH 仓库
        text = _load_card(card_path)
        if text is None:
            return 0  # 卡缺失/为空 → 静默，注入空串毫无意义
        if human:
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
            sys.stdout.write(text + "\n")
        else:
            _emit_json(text, wrapped)
    except Exception:
        return 0  # fail-open：任何异常静默退出，绝不阻塞会话
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
