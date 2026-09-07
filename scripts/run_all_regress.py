# -*- coding: utf-8 -*-
"""统一回归 runner：compileall 门禁 + 逐个执行 + 三态汇总（零第三方依赖）。

用法：
    python scripts/run_all_regress.py            # 编译门禁 + 跑全部 tests/*.py
    python scripts/run_all_regress.py --compile-only
    python scripts/run_all_regress.py --all-py   # 编译门禁覆盖 scripts/ 与 hma/
    python scripts/run_all_regress.py --filter regress_

设计要点：
  · 根目录由 __file__ 推导，不含任何硬编码绝对路径（可在任意盘符/目录下运行）
  · 三态：SYNTAX（根本跑不起来）/ FAIL（断言失败或崩溃）/ OK（干净退出）
  · 任一 SYNTAX 或 FAIL 即整体退出码 1，可直接用作门禁
"""
import os
import subprocess
import sys
import compileall
import fnmatch

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
TESTS = os.path.join(HERE, "tests")

TIMEOUT = 180


def _compile_gate(targets):
    print("=" * 72)
    print("阶段一 · 编译门禁（compileall）")
    print("=" * 72)
    broken = []
    for t in targets:
        ok = compileall.compile_dir(
            t, quiet=2, force=True,
        )
        if not ok:
            broken.append(t)
    if broken:
        print("[编译失败] %s" % ", ".join(broken))
    else:
        print("[编译通过] %d 个目录，0 语法错误" % len(targets))
    print()
    return not broken


def _list_tests(pattern):
    if not os.path.isdir(TESTS):
        return []
    names = sorted(n for n in os.listdir(TESTS) if n.endswith(".py"))
    if pattern:
        names = [n for n in names if fnmatch.fnmatch(n, "*%s*" % pattern)]
    return names


def main():
    args = sys.argv[1:]
    compile_only = "--compile-only" in args
    all_py = "--all-py" in args
    pattern = ""
    if "--filter" in args:
        i = args.index("--filter")
        if i + 1 < len(args):
            pattern = args[i + 1]

    targets = [TESTS]
    if all_py:
        targets = [os.path.join(PROJECT, "hma"), HERE]
    compile_ok = _compile_gate(targets)
    if compile_only:
        return 0 if compile_ok else 1

    names = _list_tests(pattern)
    print("=" * 72)
    print("阶段二 · 逐个执行（%d 个）" % len(names))
    print("=" * 72)

    env = dict(os.environ)
    env["PYTHONPATH"] = PROJECT
    env["PYTHONIOENCODING"] = "utf-8"

    ok_list, fail_list, syn_list = [], [], []
    for n in names:
        path = os.path.join(TESTS, n)
        try:
            subprocess.run(
                [sys.executable, "-m", "py_compile", path],
                check=True, capture_output=True, env=env, timeout=60,
            )
        except Exception:
            syn_list.append(n)
            print("[SYNTAX] %s" % n)
            continue
        try:
            r = subprocess.run(
                [sys.executable, path],
                capture_output=True, env=env, timeout=TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            fail_list.append((n, "TIMEOUT>%ds" % TIMEOUT))
            print("[FAIL  ] %s  (超时)" % n)
            continue
        if r.returncode == 0:
            ok_list.append(n)
            print("[OK    ] %s" % n)
        else:
            tail = (r.stdout or r.stderr or b"").decode("utf-8", "ignore")
            last = [l for l in tail.strip().splitlines() if l.strip()]
            fail_list.append((n, last[-1][:90] if last else "exit=%d" % r.returncode))
            print("[FAIL  ] %s" % n)

    print()
    print("=" * 72)
    print("汇总")
    print("=" * 72)
    print("  干净退出 : %d" % len(ok_list))
    print("  语法错误 : %d" % len(syn_list))
    print("  失败崩溃 : %d" % len(fail_list))
    print("  合计     : %d" % len(names))
    if syn_list:
        print("\n-- SYNTAX --")
        for n in syn_list:
            print("   %s" % n)
    if fail_list:
        print("\n-- FAIL --")
        for n, why in fail_list:
            print("   %-42s %s" % (n, why))
    print()
    if syn_list or fail_list:
        print("[RESULT] RED —— 存在语法错误或失败，门禁不通过")
        return 1
    print("[RESULT] GREEN —— 全部干净退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
