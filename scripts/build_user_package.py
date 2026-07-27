# -*- coding: utf-8 -*-
"""
build_user_package.py —— 用 WB 里的真实数据填充 HMA 的 User/profile 包。

设计对照（对齐 q-0 / q-2 决策）：
  · q-0：User 源 = 「WB 画像 + HMA 设计偏好」
      - ~/.workbuddy/MEMORY.md            → 事件 user-profile（跨项目用户画像，全量原文）
      - <workspace>/.workbuddy/memory/MEMORY.md
                                          → 事件 hma-design-prefs（抽取用户明示的偏好/定位/约定，全量原文）
  · q-2 分类铁律：关于「用户自身」的元关联内容（偏好 / 思路 / 方法论）→ 进 User 包，
    不塞进话题类目（如 项目/、其他/）。

确定性、幂等（Memory.write upsert，重跑覆盖、保留原 created）。
"""
import os
import sys
import re
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hma.hma_core import Memory

# ---- 抽取项目 MEMORY.md 中的明示约定段 ----

_SECTIONS = ["用户在研项目", "用户偏好", "项目定位", "开发阶段约定"]


def _extract_section(body, heading):
    """从 markdown 正文中抽取 ## <heading> 段（包含其下全部子节，到下一个 ## 截止）。"""
    pattern = r"^##\s+" + re.escape(heading) + r"\s*$"
    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.match(pattern, ln):
            start = i
            break
    if start is None:
        return ""
    # 收集到下一个 ## 为止
    out = [lines[start]]
    for ln in lines[start + 1:]:
        if re.match(r"^##\s+", ln):
            break
        out.append(ln)
    return "\n".join(out).strip()


def _build_user_profile(mem, cross_project_md, create_date):
    """读 ~/.workbuddy/MEMORY.md 全量原文 → 事件 user-profile。"""
    if not os.path.exists(cross_project_md):
        print("  跳过 user-profile：%s 不存在" % cross_project_md)
        return None
    with open(cross_project_md, encoding="utf-8") as f:
        body = f.read().strip()
    if not body:
        print("  跳过 user-profile：文件为空")
        return None
    # 注入溯源行
    full_body = body + "\n\n> 来源: WorkBuddy 跨项目用户画像 @ %s\n" % cross_project_md
    summary = ("WB 跨项目用户画像：学校级开发经验、git/工程化不熟、"
               "本地开发阶段先不碰 git")
    mem.write(
        id="user-profile",
        title="用户画像（跨项目）",
        summary=summary,
        aliases=["用户画像", "user-profile", "user profile"],
        tags=["user", "profile", "wb-derived"],
        linked=["hma-design-prefs"],
        body=full_body,
        created=create_date,
        updated=create_date,
        trigger="build_user_package",
    )
    return "user-profile"


def _build_design_prefs(mem, project_md, create_date):
    """解析项目 MEMORY.md，抽取明示约定段 → 事件 hma-design-prefs。"""
    if not os.path.exists(project_md):
        print("  跳过 hma-design-prefs：%s 不存在" % project_md)
        return None
    with open(project_md, encoding="utf-8") as f:
        raw = f.read()

    sections = []
    for heading in _SECTIONS:
        sec = _extract_section(raw, heading)
        if sec:
            sections.append(sec)

    if not sections:
        print("  跳过 hma-design-prefs：未找到任何 %s 段" % _SECTIONS)
        return None

    body = "\n\n".join(sections)
    full_body = body + "\n\n> 来源: WorkBuddy 项目级记忆 @ %s\n" % project_md
    summary = "用户对 HMA 的设计偏好与项目定位：%s" % " / ".join(_SECTIONS)
    mem.write(
        id="hma-design-prefs",
        title="HMA 设计偏好（用户明示）",
        summary=summary,
        aliases=["设计偏好", "hma-design-prefs", "design prefs"],
        tags=["user", "hma", "design-prefs", "preferences", "wb-derived"],
        linked=["user-profile"],
        body=full_body,
        created=create_date,
        updated=create_date,
        trigger="build_user_package",
    )
    return "hma-design-prefs"


# ---- main ----

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="用 WB 真实数据填充 HMA 的 User/profile 包（确定性、幂等）")
    ap.add_argument("--root", default="memory/用户",
                    help="HMA 记忆根（默认 memory/用户）")
    ap.add_argument("--cross-project-memory",
                    default=os.path.expanduser("~/.workbuddy/MEMORY.md"),
                    help="WB 跨项目用户画像路径")
    ap.add_argument("--project-memory",
                    help="WB 项目级 MEMORY.md 路径（默认从 cwd 推导 .workbuddy/memory/MEMORY.md）")
    a = ap.parse_args()

    if not a.project_memory:
        # 从 cwd 推导
        cwd = os.getcwd()
        a.project_memory = os.path.join(cwd, ".workbuddy", "memory", "MEMORY.md")

    today = datetime.date.today().isoformat()

    # 确保目标目录存在
    os.makedirs(a.root, exist_ok=True)
    mem = Memory(a.root)
    try:
        created = []
        r = _build_user_profile(mem, a.cross_project_memory, today)
        if r:
            created.append(r)
        r = _build_design_prefs(mem, a.project_memory, today)
        if r:
            created.append(r)
        if created:
            print("已构建 %s（%d 事件）" % (a.root, len(created)))
            # 重建索引确保一致性
            mem.rebuild()
        else:
            print("未构建任何事件")
    finally:
        mem.close()
