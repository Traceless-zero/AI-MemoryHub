# -*- coding: utf-8 -*-
"""
Veronica OC 归档检索测试 harness
================================
把「留几个测试问法来进行测试」固化成可重复运行的脚本。

用法：
    cd E:/BaiduNetdiskDownload/项目/AIMH
    python scripts/tests/test_veronica_queries.py

每条用例：(问法, 期望命中的包前缀, 期望锚点标题里出现的字样)
断言逻辑：top-1 命中的 package_id 应以期望前缀开头，且锚点标题含期望字样。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, PROJECT)

from hma.hma_core import Memory  # noqa: E402

VERONICA_DIR = os.path.join(PROJECT, "memory", "原创角色", "维罗妮卡·夏·雪莱")

# (查询词, 期望包 id（query_anchors 返回裸 id）, 期望锚点标题关键字)
TESTS = [
    ("协议X-2",     "veronica-origin", "第五阶段"),
    ("幽影核心",     "veronica-origin", "第三阶段"),
    ("圣保罗之焰",   "veronica-origin", "怪盗之夜"),   # 圣保罗之焰=怪盗之夜盗窃物（8.19 锚点结构更新）
    ("回旋镖",      "veronica-origin", "第一阶段"),    # 回旋镖计划在 origin 第一阶段（8.19 更新）
    ("战衣",        "veronica-ext",    "战衣设计"),
    ("托尼·斯塔克",  "veronica-ext",    "漫威宇宙锚点"),
    ("纽约之战",     "veronica-ext",    "漫威宇宙锚点"),
    ("自由",        "veronica-origin", "第二阶段"),
]


def fmt_top(hit):
    if not hit:
        return "  (无命中)"
    # query_anchors 返回元组：(pkg_id, anchor_title, anchor_summary, locator, score)
    if isinstance(hit, (tuple, list)):
        pid, title, summary, locator, score = (list(hit) + [None] * 5)[:5]
    else:  # 防御：若未来改成 dict
        pid = hit.get("package_id")
        title = hit.get("title") or hit.get("anchor")
        summary = hit.get("summary")
        score = hit.get("score")
    snip = (summary or "")[:40].replace("\n", " ")
    return f"  pkg={pid}  anchor='{title}'  score={score}  :: {snip}…"


def main():
    m = Memory(VERONICA_DIR)
    passed = 0
    failed = 0
    print(f"HMA 检索测试 — Veronica 归档 ({len(TESTS)} 用例)\n")

    for q, exp_pkg, exp_kw in TESTS:
        hits = m.query_anchors(q, top_k=3)
        top = hits[0] if hits else None
        if top is None:
            top_pid, top_title = "", ""
        elif isinstance(top, (tuple, list)):
            top_pid = top[0] or ""
            top_title = top[1] or ""
        else:
            top_pid = top.get("package_id") or ""
            top_title = (top.get("title") or top.get("anchor") or "")
        ok = (
            top is not None
            and top_pid.startswith(exp_pkg)
            and exp_kw in top_title
        )
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] 问：{q}")
        print(fmt_top(top))
        if not ok:
            print(f"       期望 pkg 前缀={exp_pkg}  期望锚点含='{exp_kw}'")
            # 打印次优命中，便于排查
            for h in hits[1:]:
                print("       次优:" + fmt_top(h))
        print()

    m.close()
    print(f"结果：{passed} 通过 / {failed} 失败 / 共 {len(TESTS)}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
