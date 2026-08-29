# -*- coding: utf-8 -*-
"""where.py —— HMA 路径自报脚本（即插即用的"第一公里"）。

HMA 是即插即用记忆外挂：整个 hma/ 目录 zip 给别人后，每个用户
解压位置不同。AI 启动 HMA（hma-always）时不该靠推理猜 memory/
在哪——运行本脚本一次，所有关键路径直接打给 AI。

自定位原理（零搜索、确定性）：
  本脚本随包分发，永远位于 <repo>/scripts/core/where.py，
  故 仓库根 = 本脚本所在目录的父级。不扫盘、不猜。

用法：
  python scripts/core/where.py            # 人读 / AI 读的文本报告
  python scripts/core/where.py --json     # 机器可读 JSON（供程序消费）
  python scripts/core/where.py --quiet    # 只打印 memory 根一行（供 shell 变量）

指针文件（解决"AI 连脚本都找不到"的引导问题）：
  每次运行自动把仓库根写入 ~/.hma_home（一行纯文本）。
  下一次任何 AI/工具想找 HMA，读这个固定位置即可：
    cat ~/.hma_home   →  <repo 绝对路径>
  多副本场景：以最后一次运行的为准（谁 where 谁登记）。

纯标准库，无第三方依赖。
"""
import io
import json
import os
import sys

# ---------------------------------------------------------------------------
# 自定位（零搜索、确定性）：脚本随包分发，永在 <repo>/scripts/ 下 → 父级即仓库根
# ---------------------------------------------------------------------------
_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.isdir(os.path.join(_SELF_DIR, "memory")):
    REPO = _SELF_DIR                       # 兼容：脚本被平铺到仓库根
else:
    REPO = os.path.dirname(os.path.dirname(_SELF_DIR))      # 标准位：scripts/ 的父级

HOME_POINTER = os.path.join(os.path.expanduser("~"), ".hma_home")


def collect():
    """收集全部关键路径与健康状态（确定性，只读）。"""
    memory = os.path.join(REPO, "memory")
    # 旧库兼容（R59 前的 .memory）
    if not os.path.isdir(memory) and os.path.isdir(os.path.join(REPO, ".memory")):
        memory = os.path.join(REPO, ".memory")

    info = {
        "repo": REPO,
        "memory": memory,
        "index_db": os.path.join(memory, "index.db"),
        "scripts": os.path.join(REPO, "scripts"),
        "skills": os.path.join(REPO, "skills"),
        "engine": os.path.join(REPO, "hma"),
        "rebuild_exe": os.path.join(REPO, "一键更新记忆索引.exe"),
        "cwd_for_engine": REPO,   # `python -m hma.engine ...` 须在此目录下执行
    }
    # 命名空间盘点（只列存在的目录）
    namespaces = []
    if os.path.isdir(memory):
        for name in sorted(os.listdir(memory)):
            p = os.path.join(memory, name)
            if os.path.isdir(p):
                namespaces.append(name)
    info["namespaces"] = namespaces
    # 健康检查
    info["ok"] = {
        "memory_exists": os.path.isdir(memory),
        "index_db_exists": os.path.isfile(info["index_db"]),
        "engine_exists": os.path.isdir(info["engine"]),
        "rebuild_exe_exists": os.path.isfile(info["rebuild_exe"]),
    }
    return info


def register_pointer(repo):
    """把仓库根登记到 ~/.hma_home（幂等；失败不致命）。"""
    try:
        with io.open(HOME_POINTER, "w", encoding="utf-8") as f:
            f.write(repo + "\n")
        return True
    except OSError:
        return False


def main(argv):
    info = collect()
    registered = register_pointer(info["repo"])

    if "--json" in argv:
        info["home_pointer"] = HOME_POINTER if registered else ""
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["ok"]["memory_exists"] else 1

    if "--quiet" in argv:
        print(info["memory"])
        return 0 if info["ok"]["memory_exists"] else 1

    ok = info["ok"]
    mark = lambda b: "[+]" if b else "[x]"
    lines = [
        "HMA 路径自报（供 AI 直接使用，无需推理）",
        "=" * 46,
        "仓库根        : " + info["repo"],
        "记忆库 memory : " + info["memory"] + "  " + mark(ok["memory_exists"]),
        "前台索引      : " + info["index_db"] + "  " + mark(ok["index_db_exists"]),
        "引擎 hma/     : " + info["engine"] + "  " + mark(ok["engine_exists"]),
        "脚本 scripts/ : " + info["scripts"],
        "技能 skills/  : " + info["skills"],
        "重建 EXE      : " + info["rebuild_exe"] + "  " + mark(ok["rebuild_exe_exists"]),
        "命名空间      : " + ("、".join(info["namespaces"]) or "（memory/ 不存在或为空）"),
        "-" * 46,
        "引擎调用方式  : cd \"" + info["cwd_for_engine"] + "\" && python -m hma.engine <子命令>",
        "指针文件      : " + (HOME_POINTER + "（已登记）" if registered else "（登记失败，可忽略）"),
    ]
    print("\n".join(lines))
    if not ok["memory_exists"]:
        print("\n[警告] memory/ 不存在——zip 解压不完整，或本脚本被移出 <repo>/scripts/。")
        return 1
    if not ok["index_db_exists"]:
        print("\n[提示] index.db 不存在——首次使用请先跑一次: 一键更新记忆索引.exe 或 python scripts/core/rebuild_index.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
