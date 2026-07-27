# -*- coding: utf-8 -*-
"""HMA MCP 启动器（随 HMA 仓库分发，自定位，零写死路径）。

被 WorkBuddy 的 mcp.json 调用，拉起 hma.server。两种部署形态都兼容：
  - 在仓库内运行（scripts/mcp_launch.py）：从自身 __file__ 反推仓库根。
  - 被部署到 ~/.workbuddy/ 后运行：读 where.py 登记的 ~/.hma_home 指针。
拿到仓库根后复用 scripts/where.py 解析 memory/，再拉起 hma.server。

即：用「定位脚本」(scripts/where.py) 代替写死字符串。

用法：
  python scripts/mcp_launch.py
调试（只打印解析出的 memory 根，不启动服务）：
  python scripts/mcp_launch.py --resolve-only
"""
import io
import os
import sys

HOME_POINTER = os.path.join(os.path.expanduser("~"), ".hma_home")


def _self_locate_repo():
    """从自身位置反推仓库根（在仓库内运行时可用）。

    判定用 HMA 专属标记 scripts/where.py，而不是只看 memory/ —— 因为
    ~/.workbuddy 自身也带一个 memory/（WB 的项目记忆目录），只看 memory/
    会把 WorkBuddy 配置目录误当成 HMA 仓库根，进而 import where 失败。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (here, os.path.dirname(here)):
        if os.path.isfile(os.path.join(cand, "scripts", "where.py")):
            return cand
    return None


def _pointer_repo():
    try:
        with io.open(HOME_POINTER, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def resolve():
    """返回 (repo, memory_root)，全程动态解析，无写死绝对路径。"""
    repo = _self_locate_repo() or _pointer_repo()
    if not repo or not os.path.isdir(os.path.join(repo, "memory")):
        raise SystemExit(
            "找不到 HMA 仓库根。请先在 HMA 仓库内运行一次： python scripts/where.py\n"
            "（它会把仓库根登记到 ~/.hma_home）"
        )
    if repo not in sys.path:
        sys.path.insert(0, repo)
    sp = os.path.join(repo, "scripts")
    if sp not in sys.path:
        sys.path.insert(0, sp)
    import where
    return repo, where.collect()["memory"]


def main(argv):
    repo, memory = resolve()
    if "--resolve-only" in argv:
        print(memory)
        return 0
    # 动态拉起 HMA MCP 服务（stdio），--root 不再写死
    os.environ["PYTHONPATH"] = repo + os.pathsep + os.environ.get("PYTHONPATH", "")
    sys.argv = ["hma.server", "--root", memory]
    from hma import server
    server.main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
