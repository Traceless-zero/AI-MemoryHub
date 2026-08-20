# -*- coding: utf-8 -*-
"""AIMH 端到端回归护栏（里程碑：AIMH端到端验证题集 T01-T13）。

用法：
    python scripts/tests/regress_questionset.py [--root E:/.../memory]

设计：把《AIMH端到端验证题集.txt》的确定性部分落成断言，重构/路由收敛时
不得退化。LLM 合成 faithfulness 类（T03/T05/T06/T08/T11/T12）仅记录召回
基线、不硬断言，留给人工核对（见题集「判定重点③」）。

断言分类：
  - abstain        ：resolve_query(allow_abstain, keywords) → decision∈{abstain,clarify}
  - recall_sub     ：query_anchors 的 TOP-K 中某结果 pkg_id/anchor 含期望子串
  - enumerate_sub  ：list_all_in_scope 返回的标题含期望子串
  - manual         ：仅打印 TOP-3 召回基线，不硬断言

退出码：0=全过；1=有硬断言失败。
"""
import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))   # <repo>/scripts/tests → <repo>
sys.path.insert(0, REPO)

from hma.hma_core import Memory

# ---- 题集确定性断言（期望对齐题集描述的「正确行为」）----------------------
CASES = [
    dict(id="T01", q="CEMA 的全称是什么？", mode="single",
         kw=["CEMA", "全称"], kind="recall_sub",
         expect_sub=["什么是AIMH系统"],
         note="L1/L2 锚点召回 CEMA 定义（CEMA=认知-事件驱动记忆架构）"),
    dict(id="T02", q="HMA 是不是这个项目的名字？别把它当项目名。", mode="single",
         kw=["HMA", "项目名"], kind="no_hijack",
         note="排除红线：HMA=底层架构代号，非项目名。"
              "【路由修复验证】全局 query_anchors 不再被伞包'用户数据'劫持；"
              "应召回 design-journal 域文档。注：'HMA≠项目名'的确切表述语料未直给"
              "（grep 全库无匹配），最终澄清依赖 LLM 合成（AIMH=项目名来自用户画像"
              "+ HMA=架构代号来自 design-journal），属 manual 类 faithfulness。"),
    dict(id="T03", q="在那种既要让一个本身没记忆的引擎显得有记忆、又得在模糊长句里精准"
                     "定位到对应章节的混合架构里，到底哪一层扛了理解的重活？",
         mode="single", kw=["理解层", "记忆", "章节", "架构"], kind="manual",
         note="长难句归约（人工核 faithfulness）"),
    dict(id="T04", q="QueryEnvelope 有哪几种 mode？各自干什么？", mode="enumerate",
         kw=["QueryEnvelope", "mode"], kind="recall_sub",
         expect_sub=["技术参考"],
         note="mode 语义（single/multi/enumerate），文档在《技术参考》§2.4"),
    dict(id="T05", q="为什么 AIMH 不在检索阶段做排除 A 这种减法操作？", mode="single",
         kw=["排除", "减法", "检索"], kind="manual",
         note="排除红线论证（人工核）"),
    dict(id="T06", q="single 模式和 multi 模式具体差在哪？", mode="single",
         kw=["single", "multi", "模式"], kind="manual",
         note="双轴框架（人工核）"),
    dict(id="T07", q="验证一下：AIMH 是不是用了向量数据库 / embedding 的 RAG？",
         mode="single", kw=["向量", "embedding", "RAG"], kind="manual",
         note="反向量立场：应召回零向量声明（非 abstain，域内可召回）"),
    dict(id="T08", q="询问类型的双轴框架，和哲学思路里那条理解–检索负载轴，俩是什么关系？",
         mode="multi", kw=["双轴", "负载轴", "理解", "检索"], kind="manual",
         note="跨文档关联（人工核）"),
    dict(id="T09", q="AIMH 记忆库里有没有关于量子计算最新进展的整理？", mode="single",
         kw=["量子计算"], kind="abstain",
         note="域外拒答 corpus_missing（不编造）"),
    dict(id="T10", q="把 design-journal 目录下所有设计文档的标题列出来。",
         mode="enumerate", kw=["design-journal", "设计文档"],
         scope="项目/AIMH-design-journal", kind="enumerate_sub",
         expect_sub=["什么是AIMH系统"],
         note="enumerate 全量列举（非 Top-K 截断）"),
    dict(id="T11", q="QueryEnvelope 的 keywords 硬闸，和拒答层的 corpus_missing 是怎么配合的？",
         mode="multi", kw=["keywords", "corpus_missing", "硬闸"], kind="manual",
         note="多跳/关联（人工核）"),
    dict(id="T12", q="哲学文档里 AI 侧担子重 那一节，到底在论证什么？", mode="single",
         kw=["AI", "担子重", "哲学"], kind="manual",
         note="读节推理（人工核）"),
    dict(id="T13", q="前天晚上咱们定的那个检索策略，最后用的哪种？", mode="single",
         kw=["前天晚上", "检索策略"], kind="abstain",
         note="域内模糊指代→abstain/clarify（非直拒、非编造）"),
]


def run_case(mem, c):
    if c["kind"] == "abstain":
        r = mem.resolve_query(c["q"], top_k=5, allow_abstain=True,
                              keywords=c["kw"])
        decision = r.get("decision")
        ok = decision in ("abstain", "clarify")
        detail = "decision=%s reason=%s" % (decision, r.get("reason"))
        return ok, detail
    if c["kind"] == "recall_sub":
        rows = mem.query_anchors(c["q"], top_k=5)
        got = [(p, t) for (p, t, _a, _l, _s) in rows]
        hit = any(any(sub in (p + " " + t) for sub in c["expect_sub"])
                  for (p, t) in got)
        detail = "TOP%d: %s" % (len(got), "; ".join("%s|%s" % (p, t)
                  for (p, t) in got[:3]) or "(no match)")
        return hit, detail
    if c["kind"] == "enumerate_sub":
        rows = mem.list_all_in_scope(scope=c.get("scope"))
        titles = [r[1] for r in rows]
        hit = any(any(sub in ti for sub in c["expect_sub"]) for ti in titles)
        detail = "n=%d; sample=%s" % (len(titles),
                  "; ".join(titles[:4]) or "(empty)")
        return hit, detail
    # no_hijack: 验证伞包劫持已消失（重构修复点）
    if c["kind"] == "no_hijack":
        rows = mem.query_anchors(c["q"], top_k=5)
        stems = [r[0] for r in rows]
        hijacked = any("用户数据" in s for s in stems)   # 伞包'用户数据'截胡
        ok = not hijacked
        detail = "TOP%d: %s%s" % (len(rows),
                  "; ".join(stems[:5]) or "(no match)",
                  "" if ok else "  <<< 伞包劫持未消除!")
        return ok, detail
    # manual: 仅记录召回基线（不硬断言，留人工核对 faithfulness）
    rows = mem.query_anchors(c["q"], top_k=3)
    detail = "TOP%d: %s" % (len(rows),
              "; ".join("%s|%s" % (p, t) for (p, t, _a, _l, _s) in rows)
              or "(no match)")
    return True, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(REPO, "memory"))
    args = ap.parse_args()

    mem = Memory(args.root)
    print("memory root: %s\n" % args.root)
    fails, gaps = [], []
    try:
        for c in CASES:
            try:
                ok, detail = run_case(mem, c)
            except Exception as e:
                ok, detail = False, "ERROR: %s" % e
            if c.get("known_gap"):
                # 已知缺口：当前应为红（重构目标），不计入 FAIL 退出码
                mark = "GAP " if not ok else "FIXD"
                if not ok:
                    gaps.append(c["id"])
            else:
                mark = "PASS" if ok else "FAIL"
                if not ok:
                    fails.append(c["id"])
            print("[%s] %-4s %-13s %s" % (mark, c["id"], c["kind"], c["note"]))
            print("       %s" % detail)
    finally:
        mem.close()

    print("\n==== 结果: 硬断言 %d/%d 通过, 失败=%s, 已知缺口(红态基线)=%s ====" % (
        len(CASES) - len(fails) - len(gaps), len(CASES),
        fails or "无", gaps or "无"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
