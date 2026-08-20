"""探针：实测拒答层当前状态 + 包 id 是否 8.3 串化。"""
import sys, os
sys.path.insert(0, r"E:/BaiduNetdiskDownload/项目/AIMH")

from hma.hma_core import Memory

ROOT = r"E:/BaiduNetdiskDownload/项目/AIMH/memory"

print("=== 包 id (8.3 短名检查) ===")
m_v = Memory(os.path.join(ROOT, "原创角色/维罗妮卡·夏·雪莱"))
print("Memory('memory/原创角色/维罗妮卡·夏·雪莱').package_id =", repr(m_v.package_id))
m_g = Memory(ROOT)
print("Memory('memory').package_id =", repr(m_g.package_id))

QS = [
    "红楼梦的作者是谁",          # 越域·应拒答
    "今天天气怎么样",            # 越域·应拒答
    "那个黄蓝色的宝石什么",       # gem 噪声问
    "黄蓝色的宝石",              # gem 直问
    "蓝钻",                      # gem 别名
    "圣保罗之焰值多少钱",         # gem+价值
]

print("\n=== query_anchors(allow_abstain=True) ===")
for q in QS:
    r = m_g.query_anchors(q, top_k=3, allow_abstain=True)
    if isinstance(r, dict):
        print(f"[q={q!r}] -> ABSTAIN decision={r.get('decision')} reason={r.get('reason')}")
    else:
        top = [(x[0], (x[1] or '')[:16]) for x in r[:3]]
        print(f"[q={q!r}] -> top3={top}")

print("\n=== resolve_query(allow_abstain=True) ===")
for q in QS:
    r = m_g.resolve_query(q, top_k=3, allow_abstain=True)
    d = r.get("decision")
    if d == "abstain":
        print(f"[q={q!r}] -> ABSTAIN reason={r.get('reason')}")
    else:
        res = r.get("results", [])
        print(f"[q={q!r}] -> decision={d} top3={[x[0] for x in res[:3]]}")

print("\n=== query() 主路径（无 abstain 参数，越域应吐垃圾）===")
for q in ["红楼梦的作者是谁", "今天天气怎么样", "那个黄蓝色的宝石什么"]:
    r = m_g.query(q, top_k=3)
    print(f"[q={q!r}] -> top3={[x[0] for x in r[:3]]}")

print("\n=== query_features (L1.5 属性特征归一) ===")
for q in ["黄蓝色的宝石", "蓝钻", "深海蓝橙焰钻石", "那颗钻石", "价值连城的宝石"]:
    hits = m_g.query_features(q, top_k=3)
    print(f"[q={q!r}] -> {hits}")
