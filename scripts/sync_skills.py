# -*- coding: utf-8 -*-
"""sync_skills.py —— 技能双副本同步器（确定性，无 LLM）。

HMA 的技能双副本：用户级 `~/.workbuddy/skills/` 与 项目级 `<repo>/hma/skills/`。
AI 在用户级编辑后，跑一条命令即可把整棵技能目录镜像到项目级，
省去逐文件手改 + diff 校验的 token 开销（这正是「理解归 AI、确定性归脚本」的落地）。

用法：
    python scripts/sync_skills.py diff                       # 只读报告双副本差异（不改动）
    python scripts/sync_skills.py push                       # 用户级 -> 项目级 整目录镜像
    python scripts/sync_skills.py new <名字> [一句话描述]   # 双副本新建一个技能骨架

行为（全部确定性）：
- diff：逐技能比较；输出 [OK] 一致 / [DIFF] 内容不同(列差异文件) / [ONLY-USER] 仅用户级 / [ONLY-PROJ] 仅项目级。
- push：把用户级每个技能目录 copytree 到项目级；项目级独有技能**保留不删**（避免误删）。
- new：在两侧各建 `<名字>/SKILL.md`（最小模板），供 AI 随后填充正文。
"""
import os
import sys
import shutil
import filecmp

USER_SKILLS = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills")


def proj_skills(repo_hma):
    return os.path.join(repo_hma, "skills")


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


def cmd_push(user, proj):
    os.makedirs(proj, exist_ok=True)
    for name in os.listdir(user):
        src = os.path.join(user, name)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(proj, name)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"[push] {name} -> 项目级")


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
    here = os.path.dirname(os.path.abspath(__file__))
    repo_hma = os.path.dirname(here)  # <repo>/hma
    proj = proj_skills(repo_hma)
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    a = sys.argv[1]
    if a == "diff":
        cmd_diff(USER_SKILLS, proj)
    elif a == "push":
        cmd_push(USER_SKILLS, proj)
    elif a == "new":
        if len(sys.argv) < 3:
            print("用法: sync_skills.py new <名字> [描述]")
            raise SystemExit(2)
        cmd_new(sys.argv[2], " ".join(sys.argv[3:]), USER_SKILLS, proj)
    else:
        print(__doc__)
        raise SystemExit(2)
