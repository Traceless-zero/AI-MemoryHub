# -*- coding: utf-8 -*-
"""AIMH 论文召回专项题集（西西弗斯幸福论证 / 程谦）。

用途：定量测「锚点 keywords 空置」对召回的影响。
  - 空 keywords 基线（当前状态）：先跑一遍，看 orig / review 各自落入 TOP-K 的情况。
  - 回填 keywords 后再跑一遍，对比 improvement。

设计要点：
  - orig 包正文是全文 → BM25 + about 兜底强，空 keywords 影响小（硬断言应 PASS）。
  - review 包只有 6 短锚点、about 弱（核心贡献.about="1."）→ 严重依赖本应存在的
    keywords。空置时 review 在 paper 内查询里容易被 orig 的多个高分锚点挤出 TOP-K。

断言分类（与 regress_questionset.py 一致，并加 expect_pkg）：
  - recall_sub   ：TOP-K 某结果 (pkg_id + " " + anchor_Chapter) 含 expect_sub
  - recall_pkg   ：TOP-K 某结果 pkg_id 含 expect_pkg 子串（用于 orig/review 分流判定）
  - manual       ：仅打印 TOP-5 召回基线，不硬断言
  - known_gap    ：当前应为红（空 keywords 预期退化），不计入 FAIL 退出码

退出码：0=硬断言全过；1=有硬断言失败。
"""
import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from hma.hma_core import Memory

PKG_ORIG = "文章/论文/哲学/加缪/西西弗斯幸福论证/西西弗斯幸福论证-orig"
PKG_REVIEW = "文章/论文/哲学/加缪/西西弗斯幸福论证/西西弗斯幸福论证-review"
PKG_ESSAY = "随笔/存在主义随笔"

CASES = [
    # ---- orig 硬断言：空 keywords 下也应 PASS（正文兜底强）----
    dict(id="P01", q="论文里惩罚结构是怎么拆分的？目标层和过程层分别指什么？",
         kw=["惩罚结构", "目标层", "过程层"], kind="recall_sub",
         expect_sub=["惩罚的结构"],
         note="orig 4.3 惩罚的结构——正文+about 含「目标层/过程层」，空 keywords 也应命中"),
    dict(id="P02", q="什么是姿态自由？论文怎么定义它的？",
         kw=["姿态自由"], kind="recall_sub",
         expect_sub=["姿态自由"],
         note="orig 4.4 姿态自由——Chapter 标题即命中词"),
    dict(id="P03", q="墙与草原的意象是什么意思？",
         kw=["墙与草原", "草原", "墙"], kind="recall_sub",
         expect_sub=["草原与墙", "墙的出现"],
         note="orig II/2.2——真实 Chapter 标题为「草原与墙」（词序与查询相反，但已回落该锚点）"),
    dict(id="P04", q="虚无在这篇论文里被定义成什么？",
         kw=["虚无", "时间分节符"], kind="recall_sub",
         expect_sub=["虚无是时间的分节符"],
         note="orig 2.3——Chapter 标题命中"),
    dict(id="P05", q="尼采在这篇论文里对应什么观点？",
         kw=["尼采", "热爱命运"], kind="recall_sub",
         expect_sub=["尼采：热爱命运"],
         note="orig 6.2——Chapter 标题命中"),
    dict(id="P12", q="萨特在这篇论文里对应什么？",
         kw=["萨特", "立法穹顶"], kind="recall_sub",
         expect_sub=["萨特：立法的穹顶"],
         note="orig 6.3——Chapter 标题命中"),

    # ---- review 风险点：空 keywords 预期退化（known_gap，红基线）----
    dict(id="P07", q="这篇论文的核心贡献有哪些？",
         kw=["核心贡献", "幸福去意志化", "惩罚结构二分"], kind="known_gap",
         scope=PKG_REVIEW, expect_sub=["核心贡献"],
         note="review 核心贡献.about='1.' 近乎空，无 keywords → 预期挤出 TOP-K（红基线）；"
              "回填 keywords 后应翻绿"),
    dict(id="P08", q="论文用的是什么方法思路？",
         kw=["方法思路", "极限验证", "文本学"], kind="known_gap",
         scope=PKG_REVIEW, expect_sub=["方法思路"],
         note="review 方法思路——about 为罗列但无 keywords → 预期退化（红基线）"),

    # ---- cross-doc 关联：论文 review 与用户随笔应同屏召回 ----
    dict(id="P06", q="这篇论文和用户的存在主义随笔，在加缪荒诞上有什么关联？",
         kw=["存在主义随笔", "加缪", "荒诞", "关联"], kind="recall_pkg",
         expect_pkg=["西西弗斯幸福论证-review", "存在主义随笔"],
         note="跨文档关联：review 链接到 随笔/存在主义随笔，应同屏出现"),

    # ---- manual 探针：打印基线，不硬断言 ----
    dict(id="P09", q="幸福的公共后果是什么？诸神面临什么两难？",
         kw=["公共后果", "诸神", "博弈"], kind="manual",
         note="orig V 幸福的公共后果——打印基线"),
    dict(id="P10", q="对峙型反抗和栖居型反抗有什么区别？",
         kw=["对峙型", "栖居型", "反抗谱系"], kind="manual",
         note="orig 6.5——打印基线"),
    dict(id="P11", q="荒诞被重新理解成什么？是关系效果吗？",
         kw=["荒诞", "关系效果", "可塑"], kind="manual",
         note="orig 2.x / 7.1——打印基线"),
]


def run_case(mem, c):
    scope = c.get("scope")
    if c["kind"] == "recall_sub":
        rows = mem.query_anchors(c["q"], top_k=5, package_id=scope)
        got = [(p, t) for (p, t, _a, _l, _s) in rows]
        hit = any(any(sub in (p + " " + t) for sub in c["expect_sub"])
                  for (p, t) in got)
        detail = "TOP%d: %s" % (len(got),
                  "; ".join("%s|%s" % (p.split("/")[-1], t) for (p, t) in got[:5]) or "(no match)")
        return hit, detail
    if c["kind"] == "recall_pkg":
        rows = mem.query_anchors(c["q"], top_k=5, package_id=scope)
        got = [p for (p, _t, _a, _l, _s) in rows]
        hit = all(any(exp in p for exp in c["expect_pkg"]) for p in [g for g in got])
        # 更宽松：要求每个 expect_pkg 至少在一个返回的 pkg 中出现
        hit = all(any(exp in p for p in got) for exp in c["expect_pkg"])
        detail = "TOP%d pkgs: %s" % (len(got), "; ".join(p.split("/")[-1] for p in got[:5]) or "(no match)")
        return hit, detail
    if c["kind"] == "known_gap":
        rows = mem.query_anchors(c["q"], top_k=5, package_id=scope)
        got = [(p, t) for (p, t, _a, _l, _s) in rows]
        hit = any(any(sub in (p + " " + t) for sub in c["expect_sub"])
                  for (p, t) in got)
        detail = "TOP%d: %s" % (len(got),
                  "; ".join("%s|%s" % (p.split("/")[-1], t) for (p, t) in got[:5]) or "(no match)")
        return hit, detail
    # manual
    rows = mem.query_anchors(c["q"], top_k=5, package_id=scope)
    detail = "TOP%d: %s" % (len(rows),
              "; ".join("%s|%s" % (p.split("/")[-1], t) for (p, t, _a, _l, _s) in rows)
              or "(no match)")
    return True, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(REPO, "memory"))
    args = ap.parse_args()

    mem = Memory(args.root)
    print("memory root: %s" % args.root)
    print("=== 空 keywords 基线（orig/review 锚点 keywords 均为 []）===\n")
    fails, gaps = [], []
    try:
        for c in CASES:
            try:
                ok, detail = run_case(mem, c)
            except Exception as e:
                ok, detail = False, "ERROR: %s" % e
            if c["kind"] == "known_gap":
                mark = "GAP " if not ok else "FIXD"
                if not ok:
                    gaps.append(c["id"])
            else:
                mark = "PASS" if ok else "FAIL"
                if not ok:
                    fails.append(c["id"])
            print("[%s] %-4s %-12s %s" % (mark, c["id"], c["kind"], c["note"]))
            print("       %s" % detail)
    finally:
        mem.close()

    hard_total = len(CASES) - len(gaps)
    print("\n==== 结果: 硬断言 %d/%d 通过, 失败=%s, 已知缺口(红态基线)=%s ====" % (
        hard_total - len(fails), hard_total, fails or "无", gaps or "无"))
    print("说明：GAP 为当前空 keywords 预期退化的红基线，回填 keywords 后翻绿即证明收益。")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
