# -*- coding: utf-8 -*-
"""回归：check_kw 重构（四要素确定性成员 + 契约瘦身 + 按通道发 WARN）。

锁定行为（与已验证沙箱一致）：
  (1) 去脆性：圣保罗之焰 归 锚定物品（非 关键事件）。
  (2) lint 不废：真实包 veronica-origin / 存在主义随笔 均 0 ERROR。
      随笔因 person:[{用户}] 被归叙事通道，旧 check_kw 曾误拒它（概念4维缺），现已通过。
  (3) 按通道发 WARN：叙事包只报 关键事件；(纯)概念包只报 概念4维。
      注：随笔含 person:[{用户}] 作者标签 → 归叙事通道 → 其 WARN 也是 关键事件；
      故「概念4维 WARN」用无四要素/无时间的纯概念包验证，不依赖随笔作者标签。
  (4) 强制维仍生效：keywords 全空 → 两通道都不满 → ERROR（拦截脏数据）。
  (5) check_kw5 仍正确强制确定性叙事维（用整洁包验证；真实 veronica anchor[7] 缺地点 token
      属数据缺口，check_kw5 会如实标出，脆性子串袋曾虚过它）。
  (6) _KW_* 子串袋已从模块移除（不再靠猜分类）。
用法：PYTHONPATH=. python scripts/tests/regress_fm_schema_kw.py
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(os.path.dirname(_here))
if _root not in sys.path:
    sys.path.insert(0, _root)

from hma.hma_core import EventPackage, _four_to_list
from hma import fm_schema as fm


def load_pkg_dict(fp):
    pkg = EventPackage.from_markdown(open(fp, encoding="utf-8").read(), fp)
    return dict(
        title=pkg.title, summary=pkg.summary, tags=pkg.tags, linked=pkg.linked,
        anchors=pkg.anchors, person=_four_to_list(pkg.person),
        location=_four_to_list(pkg.location), topic=_four_to_list(pkg.topic),
        event_date=pkg.event_date, pkage_created=pkg.created, pkage_updated=pkg.updated,
    )


def banner(t):
    print("\n" + "=" * 72)
    print(t)
    print("=" * 72)


def assert_eq(name, got, exp):
    ok = got == exp
    print("  [%s] %s : got=%r exp=%r" % ("PASS" if ok else "FAIL", name, got, exp))
    return ok


def main():
    root = _root
    vfp = os.path.join(root, "memory/原创角色/维罗妮卡·夏·雪莱/veronica-origin.md")
    efp = os.path.join(root, "memory/文章/随笔/存在主义随笔.md")
    veronica = load_pkg_dict(vfp)
    essay = load_pkg_dict(efp)

    all_ok = True

    banner("A. 真实包：check_kw 0 ERROR（旧 check_kw 曾误拒 随笔）")
    all_ok &= assert_eq("veronica-origin check_kw ERROR数", len(fm.check_kw(veronica)), 0)
    all_ok &= assert_eq("存在主义随笔 check_kw ERROR数", len(fm.check_kw(essay)), 0)

    banner("B. 按通道发 WARN：叙事包只报 关键事件；(纯)概念包只报 概念4维")
    vw = fm.check_kw_warn(veronica)
    all_ok &= assert_eq("veronica-origin WARN 含'关键事件'",
                        any("关键事件" in w for w in vw), True)
    all_ok &= assert_eq("veronica-origin WARN 混入'概念4维'?",
                        any("概念4维" in w for w in vw), False)
    # 纯概念包：无 person/location，event_date='—' → pkg_narrative=False → 概念通道
    concept_pkg = {
        "event_date": "—", "person": [], "location": [], "topic": [],
        "anchors": [{"Chapter": "C", "about": "x", "keywords": ["核心概念词"]}],
    }
    cw = fm.check_kw_warn(concept_pkg)
    all_ok &= assert_eq("纯概念包 WARN 含'概念4维'",
                        any("概念4维" in w for w in cw), True)
    all_ok &= assert_eq("纯概念包 WARN 混入'关键事件'?",
                        any("关键事件" in w for w in cw), False)
    print("  veronica WARN 条数=%d；纯概念包 WARN 条数=%d" % (len(vw), len(cw)))

    banner("C. 去脆性：圣保罗之焰 → 锚定物品（非 关键事件）")
    adv = {
        "event_date": "—",
        "person": [], "location": [],
        "topic": [{"圣保罗之焰": ["黄/橙", "蓝", "双色", "宝石", "价值连城"]}],
        "anchors": [{"Chapter": "X", "about": "y", "keywords": ["圣保罗之焰"]}],
    }
    topic_set = {str(k) for d in adv["topic"] for k, vs in d.items() for v in ([k] + vs)}
    cov = fm._kw_covered_narrative(
        adv["anchors"][0]["keywords"], set(), set(), topic_set, False, {"锚定物品"})
    all_ok &= assert_eq("圣保罗之焰 归 锚定物品", "锚定物品" in cov, True)
    all_ok &= assert_eq("圣保罗之焰 误归 关键事件?", "关键事件" in cov, False)

    banner("D. 强制维仍生效（keywords 为空 → 两通道都不满 → ERROR）")
    empty_nar = {
        "event_date": "2026",
        "person": [{"维罗妮卡·夏·雪莱": ["午夜魅影"]}],
        "location": [{"曼哈顿": []}], "topic": [],
        "anchors": [{"Chapter": "C", "about": "x", "keywords": []}],
    }
    all_ok &= assert_eq("叙事包空keywords→ERROR", len(fm.check_kw(empty_nar)) >= 1, True)
    empty_con = {
        "event_date": "—", "person": [], "location": [], "topic": [],
        "anchors": [{"Chapter": "C", "about": "x", "keywords": []}],
    }
    all_ok &= assert_eq("概念包空keywords→ERROR", len(fm.check_kw(empty_con)) >= 1, True)

    banner("E. check_kw5 仍正确强制（用整洁叙事包验证；不依赖真实包缺口）")
    clean_nar = {
        "event_date": "2026",
        "person": [{"维罗妮卡·夏·雪莱": ["午夜魅影"]}],
        "location": [{"曼哈顿": []}], "topic": [],
        "anchors": [{"Chapter": "C", "about": "x",
                     "keywords": ["2026", "曼哈顿", "维罗妮卡·夏·雪莱", "宝石"]}],
    }
    all_ok &= assert_eq("整洁叙事包 check_kw5 ERROR数", len(fm.check_kw5(clean_nar)), 0)

    banner("F. 无 _KW_* 子串袋残留")
    all_ok &= assert_eq("模块已无 _KW_TIME_WORDS", hasattr(fm, "_KW_TIME_WORDS"), False)
    all_ok &= assert_eq("模块已无 _KW_EVENT_WORDS", hasattr(fm, "_KW_EVENT_WORDS"), False)
    all_ok &= assert_eq("模块已无 _KW_CONCEPT_HINTS", hasattr(fm, "_KW_CONCEPT_HINTS"), False)

    print("\n" + ("全部 PASS ✓" if all_ok else "存在 FAIL ✗"))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
