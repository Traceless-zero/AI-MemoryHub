# -*- coding: utf-8 -*-
"""
Veronica OC 校准基准（20 可答 + 5 对抗）
=========================================
目的：
  1. 复现已被误删的「Veronica mini-bench」20+5 结构，作为拒答层（faithfulness gate）
     的校准基线。
  2. 断言两类核心性质：
       · 20 条可答查询 —— query_anchors 必须返回真实命中，且 allow_abstain=True
         时不得误拒答（over-refusal = 致命缺陷，必须 0）。
       · 5 条对抗查询 —— 记忆库里不存在对应内容，allow_abstain=True 时必须返回
         abstain（faithful "I don't know"），不得编造命中。
  3. 打印每条可答查询的真实落点（包 id / 锚点标题 / 置信度），便于人工核对归因。

用法：
    cd E:/BaiduNetdiskDownload/项目/AIMH
    python scripts/tests/bench_veronica_20_5.py

注意：本文件是「校准基准」，非一次性脚本，长期保留；不要丢进 to_delete/。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, PROJECT)

from hma.hma_core import Memory  # noqa: E402

VERONICA_DIR = os.path.join(PROJECT, "memory", "原创角色", "维罗妮卡·夏·雪莱")

# (查询, 期望落点的包前缀, 期望锚点标题关键字)
#  · 前缀为 "veronica-" 表示任意 Veronica 包均可（跨包同实体场景，仅校验"有答案"）。
#  · exp_kw="" 表示跳过关键字校验（该实体跨多锚点，不锁定具体小节）。
#  · 仅当 exp_pkg 为具体包且落点不符时才标 ⚠（视为真实归因偏差）。
LEGIT = [
    # —— veronica-origin（背景/起源） ——
    ("协议X-2",            "veronica-",       ""),
    ("幽影核心",            "veronica-",       "幽影核心"),
    ("圣保罗之焰",          "veronica-origin", "第四阶段"),
    ("自由",               "veronica-",       ""),
    ("红房",               "veronica-",       ""),
    ("铸造厂",              "veronica-origin", "第一阶段"),
    ("塞莱丝汀·杜·拉克",     "veronica-origin", ""),
    ("霍华德·斯塔克",        "veronica-origin", "第一阶段"),
    ("黑寡妇",              "veronica-origin", "第一阶段"),
    # —— veronica-base（核心档案/形象/信条） ——
    ("午夜魅影",            "veronica-",       ""),
    ("维罗妮卡·夏·雪莱",     "veronica-",       ""),
    ("尼克·弗瑞",           "veronica-",       ""),
    ("暗影哲学",            "veronica-base",   "信条"),
    ("精准即仁慈",          "veronica-base",   "信条"),
    ("191cm",              "veronica-base",   ""),
    # —— veronica-ext（战衣/能力/漫威锚点） ——
    ("战衣",               "veronica-ext",    ""),
    ("托尼·斯塔克",          "veronica-",       ""),
    ("纽约之战",            "veronica-ext",    "漫威宇宙锚点"),
    ("第六人",              "veronica-ext",    "漫威宇宙锚点"),
    ("武器重构",            "veronica-ext",    "能力与武装"),
]

# 5 条对抗查询：记忆库里不存在对应内容，必须 abstain
ADV = [
    "量子计算的最新发展是什么",
    "苹果公司今天的股价是多少",
    "2022年世界杯冠军是谁",
    "番茄炒蛋怎么做才好吃",
    "鲁迅的小说《故乡》讲的是什么",
]


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
    m = Memory(VERONICA_DIR)
    passed = 0
    failed = 0

    print(f"=== Veronica 校准基准：20 可答 ===\n")
    for q, exp_pkg, exp_kw in LEGIT:
        hits = m.query_anchors(q, top_k=5)
        ab = m.query_anchors(q, top_k=5, allow_abstain=True)

        # 核心断言 1：列表形式必须返回命中
        list_ok = bool(hits)
        # 核心断言 2：开启拒答层不得误拒
        no_abstain = isinstance(ab, dict) and ab.get("abstain") is False
        # 归因核对（不强制，仅提示）
        top = hits[0] if hits else None
        top_pid = (top[0] if isinstance(top, (tuple, list)) else top.get("package_id")) if top else ""
        top_title = ""
        if top:
            top_title = top[1] if isinstance(top, (tuple, list)) else (top.get("title") or top.get("anchor") or "")
        kw_ok = (exp_kw == "" or (exp_kw in (top_title or "")))
        pkg_ok = top_pid.startswith(exp_pkg)
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

    print(f"=== Veronica 校准基准：5 对抗 ===\n")
    adv_pass = 0
    for q in ADV:
        ab = m.query_anchors(q, top_k=5, allow_abstain=True)
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
