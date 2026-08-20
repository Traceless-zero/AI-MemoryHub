# -*- coding: utf-8 -*-
"""沙箱：验证 check_kw 候选重构方向（四要素确定性成员 + 契约瘦身，去 _KW_* 子串袋）。

生产代码 fm_schema.py 不动；本脚本自带候选实现 check_kw_sandbox，只对真实包 + 对抗样本
跑对比，证明：
  (1) 去脆性：圣保罗之焰 不再被误判为 关键事件，正确归 锚定物品；
  (2) lint 不废：真实 概念包(存在主义随笔) 当前被误拒，沙箱通过；
  (3) 召回无关：本脚本只测写时 lint，不动召回（召回走 BM25+锚点+四要素）。
用法：PYTHONPATH=. python scripts/tests/sandbox_check_kw_refactor.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hma.hma_core import EventPackage, _four_to_list
from hma import fm_schema as fm

import re
_YEAR_RE = fm._YEAR_RE  # 年份正则（结构性，非子串袋，保留）


def _name_universe(d, fld):
    """取四要素规范名+变体 的精确名宇宙（确定性来源）。"""
    out = set()
    for item in (d.get(fld) or []):
        if isinstance(item, dict):
            for canon, variants in item.items():
                out.add(str(canon))
                for v in (variants or []):
                    out.add(str(v))
    return out


def _kw_covered_narrative_sandbox(keywords, pkg_person, pkg_loc, pkg_topic, pkg_time_ok, applicable):
    """候选叙事分类：只靠确定性来源，零 _KW_* 子串袋。

    - 时间：年份正则 或 包级 pkg_time_ok
    - 地点：keyword ∈ 包 location 名宇宙（精确）
    - 人物：keyword ∈ 包 person 名宇宙（精确） 或 含 · 
    - 锚定物品：keyword ∈ 包 topic 名宇宙（精确） 或 残余兜底
    - 关键事件：移除（无确定性源，降为 WARNING，见 check_kw_sandbox）
    """
    covered = set()
    has_residual = False
    for raw in keywords:
        k = str(raw).strip()
        if not k:
            continue
        is_time = bool(_YEAR_RE.match(k))
        is_loc = k in pkg_loc
        is_person = (k in pkg_person) or ("·" in k)
        is_item = k in pkg_topic
        if is_time:
            covered.add("时间")
        if is_loc and "地点" in applicable:
            covered.add("地点")
        if is_person and "人物" in applicable:
            covered.add("人物")
        if is_item:
            covered.add("锚定物品")
        if not (is_time or (is_loc and "地点" in applicable)
                or (is_person and "人物" in applicable) or is_item):
            has_residual = True
    if pkg_time_ok:
        covered.add("时间")
    if has_residual:
        covered.add("锚定物品")
    return covered


def _kw_covered_concept_sandbox(keywords):
    """候选概念分类：核心概念 靠残余兜底（去掉 _KW_CONCEPT_HINTS 子串袋）。

    论证/结论/依赖/争议 无确定性源 → 降 WARNING（见 check_kw_sandbox）。
    """
    has_residual = any(str(raw).strip() for raw in keywords)
    covered = {"核心概念"} if has_residual else set()
    return covered


def check_kw_sandbox(d):
    """候选双通道契约：强制契约只保留有确定性源的维；其余降 WARNING。

    叙事强制 = {时间(pkg_time_ok) / 地点(pkg_loc非空) / 人物(pkg_person非空) / 锚定物品}
    概念强制 = {核心概念}
    关键事件、论证/结论/依赖/争议 → 仅 WARN（不再 ERROR）。
    """
    errs, warns = [], []
    anchors = d.get("anchors")
    if not isinstance(anchors, list):
        return errs, warns
    pkg_person = _name_universe(d, "person")
    pkg_loc = _name_universe(d, "location")
    pkg_topic = _name_universe(d, "topic")
    pkg_time_ok = bool(d.get("event_date")) and str(d.get("event_date")).strip() not in ("", "—")
    applicable = set()
    if pkg_time_ok:
        applicable.add("时间")
    if any(isinstance(it, dict) and it for it in (d.get("location") or [])):
        applicable.add("地点")
    if any(isinstance(it, dict) and it for it in (d.get("person") or [])):
        applicable.add("人物")
    # 包级通道类型：有 person/location 四要素 或 有时间信号 → 叙事包；否则概念包。
    # （用户模型：一个包填一个 list；通道归属靠包级类型，而非"哪个强制契约满足"——
    #  因为瘦身后 核心概念/锚定物品 靠残余恒可满足，两 list 都满足无法作判别。）
    pkg_narrative = bool(pkg_person) or bool(pkg_loc) or pkg_time_ok
    mand_nar = {"锚定物品"}
    if pkg_time_ok:
        mand_nar.add("时间")
    if "地点" in applicable:
        mand_nar.add("地点")
    if "人物" in applicable:
        mand_nar.add("人物")
    for i, a in enumerate(anchors):
        if not isinstance(a, dict):
            errs.append("ERROR anchors[%d] 须为 dict" % i)
            continue
        kws = a.get("keywords", a.get("tags"))
        if not isinstance(kws, list):
            errs.append("ERROR anchors[%d].keywords 须为 list" % i)
            continue
        cov_nar = _kw_covered_narrative_sandbox(kws, pkg_person, pkg_loc, pkg_topic, pkg_time_ok, applicable)
        cov_con = _kw_covered_concept_sandbox(kws)
        nar_ok = all(dim in cov_nar for dim in mand_nar)
        con_ok = "核心概念" in cov_con
        if nar_ok or con_ok:
            # 按包级通道类型发 WARN：叙事包只报 关键事件；概念包只报 概念4维。
            # （另一个 list 的 WARN 直接不走 —— 用户 2026-08-18：那个 list 被满足才报它的 WARN）
            if pkg_narrative and "关键事件" not in cov_nar:
                warns.append("WARN anchors[%d] 关键事件（demoted, advisory）" % i)
            if (not pkg_narrative) and ("相关论证" not in cov_con or "关键结论" not in cov_con
                                        or "前置依赖" not in cov_con or "反例或争议" not in cov_con):
                warns.append("WARN anchors[%d] 概念4维(论证/结论/依赖/争议)（demoted, advisory）" % i)
            continue
        nar_miss = [dim for dim in mand_nar if dim not in cov_nar]
        errs.append("ERROR anchors[%d] 未填满任一强制通道：叙事缺 %s；概念缺 %s"
                    % (i, "/".join(nar_miss) or "（已填满）", "核心概念" if not con_ok else "（已填满）"))
    return errs, warns


def load_pkg_dict(fp):
    pkg = EventPackage.from_markdown(open(fp, encoding="utf-8").read(), fp)
    return dict(
        title=pkg.title, summary=pkg.summary, tags=pkg.tags, linked=pkg.linked,
        anchors=pkg.anchors, person=_four_to_list(pkg.person), location=_four_to_list(pkg.location),
        topic=_four_to_list(pkg.topic), event_date=pkg.event_date,
        pkage_created=pkg.created, pkage_updated=pkg.updated,
    )


def banner(t):
    print("\n" + "=" * 72)
    print(t)
    print("=" * 72)


def main():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cases = [
        ("叙事包 veronica-origin", "memory/原创角色/维罗妮卡·夏·雪莱/veronica-origin.md"),
        ("概念包 存在主义随笔", "memory/文章/随笔/存在主义随笔.md"),
    ]
    for name, rel in cases:
        fp = os.path.join(root, rel)
        d = load_pkg_dict(fp)
        banner("%s  [%s]" % (name, rel))
        cur = fm.check_kw(d)
        san_e, san_w = check_kw_sandbox(d)
        print("  当前 check_kw  ERROR: %d" % len(cur))
        for e in cur:
            print("    ✗", e)
        print("  沙箱 check_kw   ERROR: %d  WARN: %d" % (len(san_e), len(san_w)))
        for e in san_e:
            print("    ✗", e)
        for w in san_w:
            print("    !", w)

    # ---- 对抗样本：仅含 圣保罗之焰 的锚点（概念包，无四要素、event_date='—'）----
    banner("对抗样本：锚点 keywords=[圣保罗之焰]（概念包，无 person/location，event_date='—'）")
    adv = {
        "event_date": "—",
        "person": [], "location": [],
        "topic": [{"圣保罗之焰": ["黄/橙", "蓝", "双色", "宝石", "价值连城"]}],
        "anchors": [{"Chapter": "X", "about": "y", "keywords": ["圣保罗之焰"]}],
    }
    cur_cov = fm._kw_covered_narrative(
        adv["anchors"][0]["keywords"],
        _name_universe(adv, "person"), _name_universe(adv, "location"),
        _name_universe(adv, "topic"), False, {"关键事件", "锚定物品"})
    san_cov = _kw_covered_narrative_sandbox(
        adv["anchors"][0]["keywords"],
        _name_universe(adv, "person"), _name_universe(adv, "location"),
        _name_universe(adv, "topic"), False, {"锚定物品"})
    print("  当前分类(叙事5维覆盖):", sorted(cur_cov), "  ← 圣保罗之焰 被误归:",
          "关键事件" in cur_cov)
    print("  沙箱分类(确定性):     ", sorted(san_cov), "  ← 圣保罗之焰 正确归:",
          "锚定物品" in san_cov and "关键事件" not in san_cov)
    print("\n结论：当前把 圣保罗之焰 误判为 关键事件(脆性袋'之焰')；沙箱改为确定性 锚定物品。")


if __name__ == "__main__":
    main()
