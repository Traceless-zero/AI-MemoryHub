# -*- coding: utf-8 -*-
"""sync_skills.py —— 技能双副本同步器（确定性，无 LLM）。

AIMH 的技能双副本：项目级 `<repo>/skills/`（权威源 / source of truth）与 用户级 `~/.workbuddy/skills/`。
约定：**项目级为源**，AI 在 `<repo>/skills/` 编辑后，跑 `pull` 把整棵技能目录镜像到用户级；
如需反向（在用户级临时改了再回灌项目级），用 `push`。双副本一致性校验用 `diff`。

用法：
    python scripts/core/sync_skills.py diff                       # 只读报告双副本差异（不改动）
    python scripts/core/sync_skills.py pull                       # 项目级 -> 用户级 整目录镜像（项目为源）
    python scripts/core/sync_skills.py push                       # 用户级 -> 项目级 整目录镜像（反向）
    python scripts/core/sync_skills.py new <名字> [一句话描述]   # 双副本新建一个技能骨架

行为（全部确定性）：
- diff：逐技能比较；输出 [OK] 一致 / [DIFF] 内容不同(列差异文件) / [ONLY-USER] 仅用户级 / [ONLY-PROJ] 仅项目级。
- pull：把项目级每个技能目录 copytree 到用户级；用户级独有技能**保留不删**（避免误删）。
- push：把用户级每个技能目录 copytree 到项目级；项目级独有技能**保留不删**（避免误删）。
- new：在两侧各建 `<名字>/SKILL.md`（最小模板），供 AI 随后填充正文。

注意：引擎代码包 `hma/`（及 MCP 工具 `mcp__aimh__*`）不归本同步器管，改名只针对技能 `aimh-*` 文件夹与路径引用。
"""
import os
import sys
import shutil
import filecmp

USER_SKILLS = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills")


def proj_skills(repo):
    return os.path.join(repo, "skills")


def _rel_files(d):
    out = {}
    if not os.path.isdir(d):
        return out
    for root, _, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)
            out[os.path.relpath(p, d).replace(os.sep, "/")] = p
    return out


def cmd_diff(user, proj):
    un = set(os.listdir(user)) if os.path.isdir(user) else set()
    pn = set(os.listdir(proj)) if os.path.isdir(proj) else set()
    for name in sorted(un | pn):
        up = os.path.join(user, name)
        pp = os.path.join(proj, name)
        if name not in pn:
            print(f"[ONLY-USER] {name}")
        elif name not in un:
            print(f"[ONLY-PROJ ] {name}")
        else:
            uf = _rel_files(up)
            pf = _rel_files(pp)
            diffs = []
            for rel in sorted(set(uf) | set(pf)):
                if rel not in pf or rel not in uf:
                    diffs.append(rel)
                elif not filecmp.cmp(uf[rel], pf[rel], shallow=False):
                    diffs.append(rel)
            tag = "OK " if not diffs else "DIFF"
            extra = "" if not diffs else f"  -> {diffs}"
            print(f"[{tag}] {name}{extra}")


def _copytree_overwrite(src, dst):
    """逐文件复制并覆盖，绝不 rmtree（避开环境 safe-delete 拦截，删除类操作 fail-closed）。"""
    os.makedirs(dst, exist_ok=True)
    for root, _, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_dir = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_dir, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(target_dir, f))


def _mirror(src_root, dst_root, label):
    os.makedirs(dst_root, exist_ok=True)
    for name in os.listdir(src_root):
        src = os.path.join(src_root, name)
        dst = os.path.join(dst_root, name)
        if os.path.isdir(src):
            _copytree_overwrite(src, dst)   # 覆盖式复制，旧文件就地更新、不删目录
        else:
            shutil.copy2(src, dst)
        print(f"[{label}] {name} -> {os.path.basename(dst_root)}")


def cmd_pull(user, proj):
    """项目级 -> 用户级（项目为源）。"""
    _mirror(proj, user, "pull")


def cmd_push(user, proj):
    """用户级 -> 项目级（反向）。"""
    _mirror(user, proj, "push")


def cmd_new(name, desc, user, proj):
    for base in (user, proj):
        d = os.path.join(base, name)
        os.makedirs(d, exist_ok=True)
        sk = os.path.join(d, "SKILL.md")
        if not os.path.exists(sk):
            with open(sk, "w", encoding="utf-8") as f:
                f.write(
                    f"---\nname: {name}\n"
                    f"description: >\n  {desc or '（待填充）'}\n---\n\n"
                    f"# {name}\n\n（AI 在此填充技能正文。）\n"
                )
        print(f"[new ] {sk}")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))  # scripts/core 目录
    repo = os.path.dirname(os.path.dirname(here))  # scripts/core -> scripts -> repo root
    proj = proj_skills(repo)
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    a = sys.argv[1]
    if a == "diff":
        cmd_diff(USER_SKILLS, proj)
    elif a == "push":
        cmd_push(USER_SKILLS, proj)
    elif a == "pull":
        cmd_pull(USER_SKILLS, proj)
    elif a == "new":
        if len(sys.argv) < 3:
            print("用法: sync_skills.py new <名字> [描述]")
            raise SystemExit(2)
        cmd_new(sys.argv[2], " ".join(sys.argv[3:]), USER_SKILLS, proj)
    else:
        print(__doc__)
        raise SystemExit(2)
