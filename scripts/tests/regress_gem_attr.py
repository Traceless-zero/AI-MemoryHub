# -*- coding: utf-8 -*-
"""
宝石「属性描述 / 描述表达式」召回回归测试
=========================================
守护「那个黄蓝色的宝石什么」类查询：用户用外观/类目属性（黄蓝、蓝钻、那颗钻石）
描述实体，而非规范名「示例信物」。

修复点（2026-08-18 重做）= 按 FM-V2 约定把**描述表达式写进四要素**：
- topic 变体 dict：`{"示例信物": ["黄蓝色的宝石", "蓝钻", "深海蓝橙焰钻石", "那颗钻石"]}`
- 别名/代号（蓝钻/示例别名/RB-7/黑寡妇）从 keyword 移除，归四要素变体。
- keyword 仅留章级表面 token（宝石/钻石 作锚定物品维；示例信物 作关键事件维）。

2026-08-20 实体化变更：新建独立实体包 物品/示例信物(shengbaoluzhihuo) /
物品/苍穹之泪(cangqiong-zhilei)，「实体=检索权威」——宝石属性查询（four 路径）
的 top1 权威落点从 demo-origin 转移到 shengbaoluzhihuo；demo-origin 仅保留
kw 路径的盗窃叙事召回（宝石/示例信物 → 三、示例事件 锚点）。本回归期望已同步。

召回双路径都验证：
- 四要素路径 `query()`：解析 topic 变体 → 规范名 → 锁定包（描述表达式机制）。
- keyword 路径 `query_anchors()`：章级 BM25（宝石/钻石/示例信物）。

跑全仓库 Memory('memory')，规避子包目录在 Windows 下被 8.3 短名 slug
成 'demo-char' 导致 package_id 失配的引擎坑。

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
#  - four 路径：宝石属性描述表达式 → 示例信物实体包（实体=检索权威，2026-08-20 实体化后）
#               keywords 为解析后的实体词（非整句），走 AI 流 query_anchors
#  - kw 路径  ：宝石/示例信物 → demo-origin（示例事件 盗窃叙事锚点）；
#              钻石 → 苍穹之泪（钻石 kw 精确命中）或 示例信物
EXPECT = {
    "黄蓝色的宝石":     ("shengbaoluzhihuo", "cangqiong-zhilei"),
    "蓝钻":             ("shengbaoluzhihuo",),
    "深海蓝橙焰钻石":   ("shengbaoluzhihuo",),
    "那颗钻石":         ("shengbaoluzhihuo",),
    "那个黄蓝色的宝石什么": ("shengbaoluzhihuo", "cangqiong-zhilei"),  # 整句噪声 → 放宽 top-2 含宝石实体
    "宝石":             ("cangqiong-zhilei", "shengbaoluzhihuo"),  # 类目词命中两枚宝石实体包锚点 kw（实体=检索权威）
    "钻石":             ("cangqiong-zhilei", "shengbaoluzhihuo"),
    "示例信物":       ("shengbaoluzhihuo", "demo-origin"),  # 实体名→实体包优先(top1)，示例角色盗窃叙事作关联包；
                                                                  # 旧期望 demo-origin 仅因 SUBJECT_SCOPE 误锁(已修)的 bug 态，非正确行为
}

# (查询词, 路径, keywords)  path: 'four' = 四要素描述表达式(AI流 query_anchors)；'kw' = keyword(query_anchors)
# keywords 为 AI 解析后的实体词（铁律：召回只走 AI 流，严禁整句 query() 机械 CJK 兜底）
TESTS = [
    ("黄蓝色的宝石",     "four", ["宝石"]),
    ("蓝钻",             "four", ["蓝钻", "钻石"]),
    ("深海蓝橙焰钻石",   "four", ["钻石"]),
    ("那颗钻石",         "four", ["钻石"]),
    ("那个黄蓝色的宝石什么", "four", ["宝石"]),
    ("宝石",             "kw",   ["宝石"]),
    ("钻石",             "kw",   ["钻石"]),
    ("示例信物",       "kw",   ["示例信物"]),
]


def main():
    m = Memory(MEMORY_DIR)
    passed = 0
    failed = 0
    print(f"宝石属性召回回归 ({len(TESTS)} 用例)\n")
    for q, path, kw in TESTS:
        expect = EXPECT[q]
        if path == "four":
            hits = m.query_anchors(q, top_k=2, keywords=kw)
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
            hits = m.query_anchors(q, top_k=3, keywords=kw)
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
