# -*- coding: utf-8 -*-
"""生成《入库目录清单.txt》——git add / commit / push 前对账用。

用法：
    python scripts/gen_track_manifest.py

设计：
  · 清单会过时，所以每次对账前重跑本脚本，再拿新清单对照 `git status`
  · 只读 git，不修改任何东西
  · 零第三方依赖
"""
import os
import subprocess
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "入库目录清单.txt")

# 不入库规则（路径前缀或后缀）→ 原因
DENY = [
    ("scripts/tests/", "测试脚本，用户明令不入库（2026-09-06 决策）"),
    ("__pycache__/", "字节码缓存"),
    (".pyc", "字节码缓存"),
    ("memory/index.db", "索引，可由 memory/**/*.md 全量重建"),
    (".workbuddy/", "工作区私有状态与备份"),
    ("to_delete/", "用户自管，AI 不碰"),
    ("node_modules/", "依赖目录"),
]

# 应入库白名单（目录前缀）
ALLOW = [
    ("hma/", "引擎源码"),
    ("scripts/core/", "确定性脚本"),
    ("scripts/", "根目录脚本（不含 tests/）"),
    ("skills/", "技能定义"),
    ("memory/", "记忆正文——唯一权威源"),
    ("网页控制台/", "网页控制台"),
    ("项目其余资产/", "项目资产"),
]

# 可疑 = 二进制 / 可执行 / 数据库 / 归档，只看扩展名。
# 注意：体积大的源码（如 hma/hma_core.py）不是可疑项，只进「体积提示」，
#       「要不要重构」和「要不要入库」是两件事，不可混为一谈。
SUSPECT_EXT = (".exe", ".dll", ".so", ".dylib", ".pyd", ".bin",
               ".db", ".sqlite", ".sqlite3", ".zip", ".7z", ".rar",
               ".gz", ".mp4", ".avi", ".mov")

BIG_THRESHOLD = 200 * 1024  # 体积提示阈值，仅提示，不代表不该入库


def git(*args):
    try:
        r = subprocess.run(["git"] + list(args), cwd=ROOT,
                           capture_output=True, timeout=30)
        return r.stdout.decode("utf-8", "ignore")
    except Exception:
        return ""


def main():
    tracked = [l.strip() for l in git("ls-files").splitlines() if l.strip()]
    porc = [l for l in git("status", "--porcelain").splitlines() if l.strip()]

    by_dir = {}
    for f in tracked:
        d = os.path.dirname(f) or "（根目录）"
        by_dir.setdefault(d, []).append(os.path.basename(f))

    L = []
    A = L.append
    A("=" * 74)
    A("AIMH 入库目录清单   （git add / commit / push 前对账用）")
    A("=" * 74)
    A("生成时间 : %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    A("生成方式 : python scripts/gen_track_manifest.py")
    A("当前入库 : %d 个文件" % len(tracked))
    A("")
    A("清单会过时。每次对账前先重跑上面的命令刷新本文件，再对照 git status。")
    A("")

    A("-" * 74)
    A("一、不入库（硬规则）—— 出现即为事故")
    A("-" * 74)
    for p, why in DENY:
        A("  [禁] %-22s %s" % (p, why))
    A("")

    A("-" * 74)
    A("二、应入库（目录白名单）")
    A("-" * 74)
    for p, why in ALLOW:
        A("  [收] %-22s %s" % (p, why))
    A("")

    A("-" * 74)
    A("三、当前实际入库清单（%d 个）" % len(tracked))
    A("-" * 74)
    for d in sorted(by_dir):
        A("  %s/   (%d)" % (d, len(by_dir[d])))
        for b in sorted(by_dir[d]):
            A("        %s" % b)
    A("")

    A("-" * 74)
    A("四、可疑项（二进制 / 可执行 / 数据库类型 —— 逐条确认是否该入库）")
    A("-" * 74)
    sus = [f for f in tracked if f.lower().endswith(SUSPECT_EXT)]
    for f in sorted(sus):
        fp = os.path.join(ROOT, f)
        kb = os.path.getsize(fp) / 1024.0 if os.path.isfile(fp) else 0
        A("  %8.1f KB  %s" % (kb, f))
    if not sus:
        A("  （无）")
    A("")

    A("-" * 74)
    A("五、体积提示（大源码文件，> %d KB —— 仅供参考，照常入库，非可疑）"
      % (BIG_THRESHOLD // 1024))
    A("-" * 74)
    big = []
    for f in tracked:
        if f.lower().endswith(SUSPECT_EXT):
            continue  # 二进制类已在第四节列出，不重复
        fp = os.path.join(ROOT, f)
        if not os.path.isfile(fp):
            continue
        sz = os.path.getsize(fp)
        if sz > BIG_THRESHOLD:
            big.append((sz, f))
    for sz, f in sorted(big, reverse=True):
        A("  %8.1f KB  [源码·正常] %s" % (sz / 1024.0, f))
    if not big:
        A("  （无）")
    A("")

    A("-" * 74)
    A("六、当前未提交改动（git status --porcelain）")
    A("-" * 74)
    if porc:
        for l in porc:
            A("  %s" % l)
    else:
        A("  （工作区干净）")
    A("")

    A("-" * 74)
    A("七、对账步骤")
    A("-" * 74)
    A("  1. git status --short")
    A("  2. 每个待提交文件对照第二节：目录是否在白名单内")
    A("  3. 对照第一节：确认没混入禁用路径")
    A("  4. 对照第四节：大文件与 exe/db 逐个确认")
    A("  5. 全部通过再 git add / commit")
    A("")

    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("已生成: %s" % OUT)
    print("  入库 %d 个 / 可疑(二进制类) %d 个 / 体积提示 %d 个 / 未提交改动 %d 条"
          % (len(tracked), len(sus), len(big), len(porc)))


if __name__ == "__main__":
    main()
