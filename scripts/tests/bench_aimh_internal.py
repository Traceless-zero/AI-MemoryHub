# -*- coding: utf-8 -*-
"""
AIMH 项目内部校准基准（架构 + 用户画像，回归 + 展示双用途）
===============================================================
目的：
  1. 在 LoCoMo（外部通用基准）之外，做一套考 AIMH **自身项目知识** 的题集，
     作为代码/文档改动后的**回归护栏**，也能在面试/演示时当场证明：
       · AIMH 记得住自己项目的关键事实（架构 / 红线 / 基准 / 用户画像）；
       · 且对记忆库里没有的域外问题，拒答层正确 abstain（敢说不知道）。
  2. 断言两类核心性质（对齐 bench_veronica_20_5.py 的格式）：
       · 可答查询 —— query_anchors 必须返回真实命中，且 allow_abstain=True
         时不得误拒答（over-refusal = 致命缺陷，必须 0）。
       · 对抗查询 —— 记忆库里不存在对应内容，allow_abstain=True 时必须返回
         abstain（faithful "I don't know"），不得编造命中。
  3. 打印每条可答查询的真实落点（包 id / 锚点标题 / 置信度），便于人工核对归因。

覆盖范围（用户拍板）：
  · 架构与决策：memory/项目/AIMH-design-journal/ 下的设计期刊包。
  · 用户画像与求职定位：memory/用户/用户数据.md、memory/用户/待办事项.md。
  · 不含 OC 维罗妮卡。

检索特性说明（诚实）：
  AIMH 当前是**特征 / BM25 式宽泛检索**，多查询会命中主架构文档
  `什么是AIMH系统`；归因（命中哪个具体包）偏宽。因此本 bench 的
  **硬指标 = 有命中 + 不误拒**；归因（exp_pkg / exp_kw）仅作软提示（⚠），
  不影响 PASS/FAIL——这与 bench_veronica_20_5.py 一致。

用法：
    cd E:/BaiduNetdiskDownload/项目/AIMH
    python scripts/tests/bench_aimh_internal.py
  注意：依赖 memory/index.db 为最新（品牌清扫等改动 front-matter 后需先
        跑「一键更新记忆索引.exe」或 scripts/core/rebuild_index.py 重建索引）。

本文件是「校准基准」，非一次性脚本，长期保留；不要丢进 to_delete/。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, PROJECT)

from hma.hma_core import Memory  # noqa: E402

# 指向 memory/ 仓库根（package_id="" → 全库检索），才能真实覆盖
# design-journal（架构）+ memory/用户/（用户画像）两类包。
# 注：若只指 design-journal 子目录，Memory.package_id 会限定作用域，
#     query_anchors 仅搜该包，用户画像事实（在 memory/用户/）将不可达。
MEMORY_DIR = os.path.join(PROJECT, "memory")

# (查询, 期望落点包 stem, 期望锚点标题关键字)
#  · exp_pkg 为具体包 stem（如 "什么是AIMH系统" / "用户数据" / "待办事项"）；
#    仅作归因软提示，不匹配只标 ⚠，不致命。
#  · exp_kw="" 表示跳过关键字校验。
#  · 硬断言只看：列表形式有命中 且 开启拒答层时未误拒。
LEGIT = [
    # —— 架构与决策（design-journal） ——
    ("AIMH 是什么类型的记忆架构？",          "什么是AIMH系统", "事件驱动"),
    ("AIMH 的四要素是哪四个字段？",           "什么是AIMH系统", "四要素"),
    ("AIMH 为什么叫泥沼变清水？",             "用户操作手册",   "泥沼"),
    ("CEMA 是哪几个铁律？",                   "什么是AIMH系统", "CEMA"),
    ("AIMH 的检索三级漏斗 L1 L2 L3 分别是什么？", "什么是AIMH系统", "三级漏斗"),
    ("AIMH 的 resolver 循环做什么？",          "什么是AIMH系统", "resolver"),
    ("AIMH 是零-ML 无向量的检索吗？",          "什么是AIMH系统", "零-ML"),
    ("AIMH 在 LoCoMo 上的 recall@30 是多少？", "什么是AIMH系统", "LoCoMo"),
    ("AIMH 的理解层到底是什么？",              "什么是AIMH系统", "理解层"),
    ("AIMH 的拒答层有几道闸门？",              "index.db存储规格", "拒答"),
    # —— 用户画像与求职定位（memory/用户/） ——
    ("用户的学历是什么？",                     "用户数据",       "大专"),
    ("用户求职主要投什么方向？",               "待办事项",       "作品集"),
    ("用户自我定位是什么角色？",               "用户数据",       "架构师"),
    ("用户的代码是怎么实现的？",               "用户数据",       "vibe coding"),
    ("用户的哲学随笔是谁写的？",               "用户数据",       "手写"),
    ("用户对 git 熟吗？",                      "用户数据",       "git"),
]

# 5 条对抗查询：记忆库里不存在对应内容，必须 abstain
ADV = [
    "太阳系有几颗行星",
    "比特币今天的价格是多少",
    "《红楼梦》的作者是谁",
    "怎么做红烧肉",
    "珠穆朗玛峰有多高",
]

# 对抗组走「真·功能接口」(keywords=)，模拟 AI 解析出的复合实体。
# 硬拒答闸(corpus_missing_entity) 仅在 AI 接口模式启用；机械拆词不可靠。
ADV_AI_KEYWORDS = {
    "太阳系有几颗行星": ["太阳系"],
    "比特币今天的价格是多少": ["比特币"],
    "《红楼梦》的作者是谁": ["红楼梦"],
    "怎么做红烧肉": ["红烧肉"],
    "珠穆朗玛峰有多高": ["珠穆朗玛峰"],
}


def fmt_top(top):
    if not top:
        return "  (无命中)"
    if isinstance(top, (tuple, list)):
        pid, title = (list(top) + [None, None])[:2]
    else:
        pid = top.get("package_id")
        title = top.get("title") or top.get("anchor")
    return f"  pkg={pid}  anchor='{title}'"


def main():
    m = Memory(MEMORY_DIR)
    passed = 0
    failed = 0

    print(f"=== AIMH 内部基准：{len(LEGIT)} 可答（架构 + 用户画像） ===\n")
    for q, exp_pkg, exp_kw in LEGIT:
        hits = m.query_anchors(q, top_k=5)
        ab = m.query_anchors(q, top_k=5, allow_abstain=True)

        list_ok = bool(hits)
        no_abstain = isinstance(ab, dict) and ab.get("abstain") is False
        top = hits[0] if hits else None
        top_pid = (top[0] if isinstance(top, (tuple, list)) else top.get("package_id")) if top else ""
        top_title = ""
        if top:
            top_title = top[1] if isinstance(top, (tuple, list)) else (top.get("title") or top.get("anchor") or "")
        kw_ok = (exp_kw == "" or (exp_kw in (top_title or "")))
        pkg_ok = (exp_pkg == "" or top_pid.startswith(exp_pkg))
        attr_ok = pkg_ok and kw_ok
        conf = ab.get("confidence") if isinstance(ab, dict) else "?"

        ok = list_ok and no_abstain
        passed += ok
        failed += (not ok)
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] 问：{q}")
        print(fmt_top(top))
        print(f"  confidence={conf}  abstain={ab.get('abstain') if isinstance(ab,dict) else 'n/a'}"
              f"  期望包={exp_pkg} 期望kw='{exp_kw}' 归因{'✓' if attr_ok else '⚠'}")
        if not ok:
            print(f"        >>> 致命：可答查询被拒答或空命中！")
        print()

    print(f"=== AIMH 内部基准：{len(ADV)} 对抗（域外，应拒答） ===\n")
    adv_pass = 0
    for q in ADV:
        kw = ADV_AI_KEYWORDS.get(q)
        ab = m.query_anchors(q, top_k=5, allow_abstain=True, keywords=kw)
        is_dict = isinstance(ab, dict)
        abstain = is_dict and ab.get("abstain") is True
        reason = ab.get("reason") if is_dict else "?"
        ok = abstain
        adv_pass += ok
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] 问：{q}")
        print(f"  abstain={abstain}  reason={reason}")
        if not ok:
            print(f"        >>> 致命：对抗查询未拒答，可能编造命中！")
        print()

    m.close()
    total_legit = len(LEGIT)
    total_adv = len(ADV)
    print("=" * 56)
    print(f"可答：{passed}/{total_legit} 通过（要求 0 误拒）")
    print(f"对抗：{adv_pass}/{total_adv} 通过（要求 0 漏拒）")
    all_ok = (passed == total_legit) and (adv_pass == total_adv)
    print("总判定：", "ALL GREEN ✅" if all_ok else "存在失败 ❌")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
