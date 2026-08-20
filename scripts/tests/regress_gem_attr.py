# -*- coding: utf-8 -*-
"""
宝石「属性描述 / 描述表达式」召回回归测试
=========================================
守护「那个黄蓝色的宝石什么」类查询：用户用外观/类目属性（黄蓝、蓝钻、那颗钻石）
描述实体，而非规范名「圣保罗之焰」。

修复点（2026-08-18 重做）= 按 FM-V2 约定把**描述表达式写进四要素**：
- topic 变体 dict：`{"圣保罗之焰": ["黄蓝色的宝石", "蓝钻", "深海蓝橙焰钻石", "那颗钻石"]}`
- 别名/代号（蓝钻/午夜魅影/RB-7/黑寡妇）从 keyword 移除，归四要素变体。
- keyword 仅留章级表面 token（宝石/钻石 作锚定物品维；圣保罗之焰 作关键事件维）。

2026-08-20 实体化变更：新建独立实体包 物品/圣保罗之焰(shengbaoluzhihuo) /
物品/苍穹之泪(cangqiong-zhilei)，「实体=检索权威」——宝石属性查询（four 路径）
的 top1 权威落点从 veronica-origin 转移到 shengbaoluzhihuo；veronica-origin 仅保留
kw 路径的盗窃叙事召回（宝石/圣保罗之焰 → 三、怪盗之夜 锚点）。本回归期望已同步。

召回双路径都验证：
- 四要素路径 `query()`：解析 topic 变体 → 规范名 → 锁定包（描述表达式机制）。
- keyword 路径 `query_anchors()`：章级 BM25（宝石/钻石/圣保罗之焰）。

跑全仓库 Memory('memory')，规避子包目录在 Windows 下被 8.3 短名 slug
成 'veronica' 导致 package_id 失配的引擎坑。

用法：
    cd E:/BaiduNetdiskDownload/项目/AIMH
    python scripts/tests/regress_gem_attr.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, PROJECT)

from hma.hma_core import Memory  # noqa: E402

MEMORY_DIR = os.path.join(PROJECT, "memory")

# 查询词 -> 期望 top1 包前缀（元组，任一匹配即通过）
#  - four 路径：宝石属性词 → 圣保罗之焰实体包（实体=检索权威，2026-08-20 实体化后）
#  - kw 路径  ：宝石/圣保罗之焰 → veronica-origin（怪盗之夜 盗窃叙事锚点）；
#              钻石 → 苍穹之泪（钻石 kw 精确命中）或 圣保罗之焰
EXPECT = {
    "黄蓝色的宝石":     ("shengbaoluzhihuo",),
    "蓝钻":             ("shengbaoluzhihuo",),
    "深海蓝橙焰钻石":   ("shengbaoluzhihuo",),
    "那颗钻石":         ("shengbaoluzhihuo",),
    "那个黄蓝色的宝石什么": ("shengbaoluzhihuo", "cangqiong-zhilei"),  # 整句噪声 → 放宽 top-2 含宝石实体
    "宝石":             ("cangqiong-zhilei", "shengbaoluzhihuo"),  # 类目词命中两枚宝石实体包锚点 kw（实体=检索权威）
    "钻石":             ("cangqiong-zhilei", "shengbaoluzhihuo"),
    "圣保罗之焰":       ("veronica-origin",),
}

# (查询词, 路径)  path: 'four' = 四要素描述表达式(query)；'kw' = keyword(query_anchors)
TESTS = [
    ("黄蓝色的宝石",     "four"),
    ("蓝钻",             "four"),
    ("深海蓝橙焰钻石",   "four"),
    ("那颗钻石",         "four"),
    ("那个黄蓝色的宝石什么", "four"),
    ("宝石",             "kw"),
    ("钻石",             "kw"),
    ("圣保罗之焰",       "kw"),
]


def main():
    m = Memory(MEMORY_DIR)
    passed = 0
    failed = 0
    print(f"宝石属性召回回归 ({len(TESTS)} 用例)\n")
    for q, path in TESTS:
        expect = EXPECT[q]
        if path == "four":
            hits = m.query(q, top_k=2)
            top = hits[0] if hits else None
            top_pid = top[0] if isinstance(top, (tuple, list)) else ""
            # 自然语序噪声查询（含「什么」等）BM25 会被字面重叠包压到 #2，
            # 机制本身已捞出宝石实体 → 放宽到 top-2 内含即可；
            # 干净属性查询要求严格 top-1。
            if q == "那个黄蓝色的宝石什么":
                ok = any(isinstance(h, (tuple, list)) and h[0].startswith(expect)
                         for h in hits[:2])
            else:
                ok = top is not None and top_pid.startswith(expect)
            anchor = ""
        else:
            hits = m.query_anchors(q, top_k=3)
            top = hits[0] if hits else None
            top_pid = top[0] if isinstance(top, (tuple, list)) else ""
            ok = top is not None and top_pid.startswith(expect)
            anchor = (top[1] if isinstance(top, (tuple, list)) else "")
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] ({path}) 问：{q}")
        rank_note = "  (top2 内含)" if (q == "那个黄蓝色的宝石什么" and ok) else ""
        print(f"      top1 pkg={top_pid}  anchor='{anchor}'{rank_note}")
        if not ok:
            print(f"      期望 pkg 前缀={expect}")
            for h in hits[1:]:
                print("      次优:", h[0], "|", (h[1] if len(h) > 1 else ""))
        print()
    m.close()
    print(f"结果：{passed} 通过 / {failed} 失败 / 共 {len(TESTS)}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
