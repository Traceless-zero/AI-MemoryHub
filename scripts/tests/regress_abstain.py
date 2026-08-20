"""拒答层 + 属性特征约定 回归（锁定 2026-08-18 两处修复）。

TESTS:
  A1 query_anchors(allow_abstain=True) 合法域内查询 -> 不拒答且命中 veronica-origin
     （锁 _relevance_filter over-abstain 修复：此前有效命中被 grounding 膨胀的
      阈值误杀→empty_pool 过度拒答）
  A2 query_anchors(allow_abstain=True) 越域查询 -> 拒答
  B1 resolve_query(allow_abstain=True, ai_mode keywords) 判别实体不在语料 -> 拒答
     （锁 resolve_query 主路径补机械/AI 拒答闸）
  C1 query_features 属性特征归一：黄蓝色的宝石 -> 圣保罗之焰
     （锁「描述表达式=属性特征分解」约定，非整句查询照搬）
"""
import sys, os
sys.path.insert(0, r"E:/BaiduNetdiskDownload/项目/AIMH")
from hma.hma_core import Memory

ROOT = r"E:/BaiduNetdiskDownload/项目/AIMH/memory"
m = Memory(ROOT)

passed = failed = 0
def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}  {detail}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {detail}")

# A1 合法域内查询不拒答 + 命中
r = m.query_anchors("黄蓝色的宝石", top_k=1, allow_abstain=True)
abstain = isinstance(r, dict) and r.get("abstain")
ans = r.get("answer") if isinstance(r, dict) else r
pkg = ans[0][0] if ans else None
# 2026-08-20 实体化后：宝石属性查询权威落点 = 独立实体包（shengbaoluzhihuo/cangqiong-zhilei），
# veronica-origin 仍合法（怪盗之夜 锚点）。核心锁点 = 域内不拒答（over-abstain 修复）。
GEM_PKGS = ("shengbaoluzhihuo", "cangqiong-zhilei", "veronica-origin")
check("A1 域内不拒答+命中宝石实体",
      (not abstain) and pkg is not None and pkg.startswith(GEM_PKGS),
      f"abstain={abstain} top1={pkg}")

# A2 越域拒答
r2 = m.query_anchors("今天天气怎么样", top_k=1, allow_abstain=True)
check("A2 越域拒答",
      isinstance(r2, dict) and bool(r2.get("abstain")),
      f"reason={r2.get('reason') if isinstance(r2,dict) else 'n/a'}")

# B1 resolve_query ai_mode 拒答（判别实体不在语料）
r3 = m.resolve_query("这个实体存在吗", top_k=1, allow_abstain=True,
                     keywords=["量子计算拓扑纠错xyz不存在词"])
check("B1 resolve_query ai_mode 拒答",
      r3.get("decision") == "abstain",
      f"decision={r3.get('decision')} reason={r3.get('reason')}")

# C1 属性特征归一
feats = m.query_features("黄蓝色的宝石", top_k=1)
locked = feats[0] if feats else None
check("C1 属性特征归一->圣保罗之焰",
      locked is not None and "圣保罗之焰" in locked,
      f"locked={locked}")

print(f"\n结果：{passed} 通过 / {failed} 失败 / 共 {passed+failed}")
sys.exit(1 if failed else 0)
