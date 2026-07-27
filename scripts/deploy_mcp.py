# -*- coding: utf-8 -*-
"""把 HMA 的 MCP 连接器配置部署到 WorkBuddy（零写死 HMA 仓库路径）。

HMA 是即插即用记忆外挂：仓库可解压到任意位置。本脚本把 MCP 启动器
复制到 WorkBuddy 配置目录（~/.workbuddy/），并写出 mcp.json 指向它——
指向的是稳定的 ~/.workbuddy/ 路径，不含 HMA 仓库绝对路径，故换机器 /
移动仓库都不用改配置。仓库根本身靠 ~/.hma_home 指针 + scripts/where.py
在运行时动态解析。

幂等：可重复跑；只更新 mcpServers.hma，保留 mcp.json 里其它连接器。

用法：
  python scripts/deploy_mcp.py            # 部署（复制启动器 + 合并写出 mcp.json + 登记指针）
  python scripts/deploy_mcp.py --dry-run  # 只打印将写出的配置，不落盘
"""
import io
import os
import sys
import shutil

REPO = os.path.dirname(os.path.abspath(__file__))   # <repo>/scripts
REPO = os.path.dirname(REPO)                          # <repo>
WB_HOME = os.path.join(os.path.expanduser("~"), ".workbuddy")
LAUNCHER_DST = os.path.join(WB_HOME, "hma_mcp_launch.py")
MCP_JSON = os.path.join(WB_HOME, "mcp.json")


def _managed_python():
    """扫描托管 python 目录，挑最新版本；找不到则回退 'python'（交环境决定）。

    不写死具体版本号，保证换机器/升级 python 后依旧可用。
    """
    base = os.path.join(WB_HOME, "binaries", "python", "versions")
    if os.path.isdir(base):
        for v in sorted(os.listdir(base), reverse=True):
            p = os.path.join(base, v, "python.exe")
            if os.path.isfile(p):
                return p
    return "python"


def build_hma_server():
    return {
        "command": _managed_python(),
        "args": [LAUNCHER_DST],
        "disabled": False,
    }


def deploy(dry_run=False):
    import json
    os.makedirs(WB_HOME, exist_ok=True)

    # 0) 登记 ~/.hma_home 指针（让部署后的启动器运行时能定位仓库）
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    sp = os.path.join(REPO, "scripts")
    if sp not in sys.path:
        sys.path.insert(0, sp)
    try:
        import where
        where.register_pointer(REPO)
    except Exception as e:
        print("[warn] 登记 ~/.hma_home 失败（启动器将改由自定位兜底）: %s" % e)

    # 1) 复制启动器到 WorkBuddy 配置目录（源 = 仓库内的 canonical 版）
    src = os.path.join(REPO, "scripts", "mcp_launch.py")
    if dry_run:
        print("[dry-run] 将复制 %s -> %s" % (src, LAUNCHER_DST))
    else:
        shutil.copyfile(src, LAUNCHER_DST)

    # 2) 合并写出 mcp.json（只动 mcpServers.hma，保留其它连接器）
    cfg = {"mcpServers": {"hma": build_hma_server()}}
    if os.path.isfile(MCP_JSON):
        try:
            with io.open(MCP_JSON, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    else:
        existing = {}
    existing.setdefault("mcpServers", {})
    existing["mcpServers"]["hma"] = cfg["mcpServers"]["hma"]
    text = json.dumps(existing, ensure_ascii=False, indent=2)

    if dry_run:
        print("[dry-run] 将写出 %s :\n%s" % (MCP_JSON, text))
        return 0

    with io.open(MCP_JSON, "w", encoding="utf-8") as f:
        f.write(text)
    print("已部署 HMA MCP 配置 -> %s" % MCP_JSON)
    print("启动器 -> %s" % LAUNCHER_DST)
    print("下一步：在 WorkBuddy 连接器管理页点「信任」激活（新窗口生效）。")
    return 0


def main(argv):
    return deploy(dry_run="--dry-run" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
