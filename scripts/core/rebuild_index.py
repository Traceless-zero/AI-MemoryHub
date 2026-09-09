# -*- coding: utf-8 -*-
"""一键更新记忆索引 —— 双击即用的单窗口控制台版。

打开 EXE 后在一个控制台窗口里逐条显示重建进度：
  - 成功 → 显示完成，停留 2 秒自动关闭（用户无需操作）
  - 失败 → 显示错误，等用户按回车关闭（确保错误可见）
全程单窗口、不闪烁、无子进程调用。

确定性全量重建（零 AI、零 token）：
  1) 扫 memory/ 下所有事件 .md 的 front-matter → 重建 index.db
     （复用 hma.hma_core.Memory.rebuild_all，progress 回调逐包回报）
  注：不生成目录结构树（属派生缓存，避免污染仓库）。

自动化场景（管道 / 定时 / CI）：设 HMA_NO_GUI=1 或带 --no-gui，
退回纯 stdout 输出，不 sleep 不等键，退出码反映成功/失败。

为什么不 Tk GUI（曾尝试过，放弃）：
  Tk 在 PyInstaller 打包环境下不稳定——Tcl/Tk 运行时文件易缺失，
  导致 import tkinter 或 tk.Tk() 建窗时半失败、闪现后崩、退回无头。
  混元3 加的"withdraw+deiconify 单根窗"治标不治本。控制台模式是
  最稳定、最接近"游戏启动器那种单窗口跑完自关"的方案。
"""
import os
import sys
import time

REPO_HINT = "memory"  # EXE 须置于 <repo>/ 下（与 memory/ 同级）


# ---------------------------------------------------------------------------
# 路径解析
# ---------------------------------------------------------------------------
def _frozen():
    return getattr(sys, "frozen", False)


def _exe_dir():
    """定位 memory/ 所在仓库根（EXE / 脚本的父级目录）。

    - EXE 放 <repo>/ 下：dirname(executable) 即 <repo>，其下 memory/ 存在。
    - 源码脚本放 <repo>/scripts/ 下：父级 <repo> 含 memory/。
    - 回退：当前工作目录含 memory/ 时用 cwd；否则用脚本/EXE 自身目录。
    """
    here = (os.path.dirname(os.path.abspath(sys.executable)) if _frozen()
             else os.path.dirname(os.path.abspath(__file__)))
    for cand in (here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        if os.path.isdir(os.path.join(cand, REPO_HINT)):
            return cand
    if os.path.isdir(os.path.join(os.getcwd(), REPO_HINT)):
        return os.getcwd()
    return here


# 源码模式：把仓库根注入 path，使 `from hma.hma_core import ...` 可解析
# （冻结 EXE 由 PyInstaller 打包自带，不受影响）。
sys.path.insert(0, _exe_dir())
from hma.hma_core import Memory


# ---------------------------------------------------------------------------
# 标记符号：检测 stdout 能否打印 ✓/✗，不能就降级 ASCII
# ---------------------------------------------------------------------------
_OK_MARK = "✓ "
_FAIL_MARK = "✗ "
try:
    "✓✗".encode(sys.stdout.encoding or "ascii")
except (UnicodeEncodeError, LookupError, TypeError):
    _OK_MARK = "[+] "
    _FAIL_MARK = "[x] "


# ---------------------------------------------------------------------------
# 核心：确定性重建（progress 回调由控制台 / 自动化模式注入）
# ---------------------------------------------------------------------------
# 注：rebuild 不再自动派生/合并锚点。全库锚点已由人工手写扎实（front-matter
# V2 契约），机械派生会覆盖人工成果。derive 仅由用户显式跑 `engine derive`
# 命令触发（见 hma/engine/dispatch.py）。
def main(argv, progress=None):
    """返回 (ok: bool, summary: str)。progress(stage, msg) 用于逐条回报。"""
    repo = _exe_dir()
    # 顺带把仓库根登记到 ~/.hma_home：让 aimh-* 技能 / mcp_launch 免路径推理直接定位
    # （即"白痴自动化获取"——双击 EXE 即完成路径登记，无需手动跑 where.py）
    try:
        _w = os.path.join(repo, "scripts", "core", "where.py")
        if os.path.isfile(_w):
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location("where", _w)
            _where = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_where)
            _where.register_pointer(repo)
    except Exception:
        pass  # 登记失败不致命：技能/启动器有 where.py 自定位兜底
    # 源码模式（python scripts/core/rebuild_index.py）下，把仓库根加入 path，
    # 使 `from hma.hma_core import Memory` 可解析；冻结 EXE 由 PyInstaller
    # 打包自带，不受影响。
    if repo not in sys.path:
        sys.path.insert(0, repo)
    mem = os.path.join(repo, REPO_HINT)
    if not os.path.isdir(mem):
        return False, "找不到 memory/ 目录：%s" % mem
    if progress:
        progress("init", "定位记忆库：%s" % mem)
    # 先跑主题视图派生（开发日志.md / 主题索引.md），让重建把派生物一并索引
    try:
        _d = os.path.join(repo, "scripts", "core", "derive_topic_views.py")
        if os.path.isfile(_d):
            import importlib.util as _ilu2
            _spec2 = _ilu2.spec_from_file_location("derive_topic_views", _d)
            _dtv = _ilu2.module_from_spec(_spec2)
            _spec2.loader.exec_module(_dtv)
            _dtv.derive(repo, progress=progress)
    except Exception as e:
        if progress:
            progress("topic-views-err", "主题视图派生跳过：%s" % e)
    try:
        m = Memory(mem)
        try:
            cnt = m.rebuild_all(progress=progress)
        finally:
            m.close()
        summary = "已重建 %d 条事件索引" % cnt
        return True, summary
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


# ---------------------------------------------------------------------------
# 控制台模式：单窗口逐条打印，成功自动关，失败等回车
# ---------------------------------------------------------------------------
def _run_console():
    """双击 EXE 默认走这：可见控制台窗口，跑完自动/手动关闭。"""
    def progress(stage, msg):
        mark = _OK_MARK if stage != "error" else _FAIL_MARK
        try:
            print(mark + msg)
            sys.stdout.flush()
        except Exception:
            pass          # stdout 被关（如点击 X）则忽略，不崩

    print("=" * 56)
    print("  一键更新记忆索引")
    print("=" * 56)
    ok, msg = main([sys.argv[0]], progress=progress)
    print("-" * 56)
    if ok:
        print(_OK_MARK + "完成：" + msg)
        print("\n  窗口将在 2 秒后自动关闭…")
        time.sleep(2)
        return 0
    else:
        print(_FAIL_MARK + "失败：" + msg)
        try:
            input("\n  按回车键关闭…")
        except (EOFError, KeyboardInterrupt):
            pass
        return 1


# ---------------------------------------------------------------------------
# 自动化模式：纯 stdout，不 sleep 不等键（HMA_NO_GUI=1 / --no-gui）
# ---------------------------------------------------------------------------
def _run_auto():
    """管道 / 定时 / CI：纯 stdout，退出码反映成功/失败。"""
    def progress(stage, msg):
        mark = "[+] " if stage != "error" else "[x] "
        try:
            print(mark + msg)
            sys.stdout.flush()
        except Exception:
            pass
    ok, msg = main([sys.argv[0]], progress=progress)
    print(("[DONE] " if ok else "[FAIL] ") + msg)
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    no_interactive = (os.environ.get("HMA_NO_GUI") == "1") or ("--no-gui" in sys.argv)
    if no_interactive:
        sys.exit(_run_auto())
    sys.exit(_run_console())
