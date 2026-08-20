"""临时演示：跑剥离后的 core（hma_core 继承 mechanical.Mixin），
AI 理解层本应交付的 keywords 由本脚本手动填（零-ML 契约：引擎不调模型）。

对比：
  A. AI-keywords 路径（keywords=手动填的规范实体词列表）—— 最优路径
  B. 机械路径（keywords=None → _understand_query 兜底）
"""
import sys, os
REPO = r"E:\BaiduNetdiskDownload\项目\AIMH"
sys.path.insert(0, REPO)
from hma.hma_core import Memory

ROOT = os.path.join(REPO, "memory")
m = Memory(ROOT)

n = m._conn().execute("SELECT COUNT(*) FROM events").fetchone()[0]
print(f"[init] Memory(root={ROOT!r})  loaded, events={n}")

# 一条在库内确有答案的查询
Q = "圣保罗之焰这颗宝石到底长什么样、什么颜色"

# A. AI-keywords 路径：手动填「AI 理解层」解析出的规范实体词
AI_KW = ["圣保罗之焰", "宝石", "黄", "橙", "蓝", "双色", "价值连城"]
print(f"\n=== A. AI-keywords 路径 (keywords={AI_KW}) ===")
ra = m.query_anchors(Q, top_k=3, keywords=AI_KW)
for pkg, title, about, loc, score in ra:
    print(f"  [{score:.3f}] {pkg}  |  {title}")
    print(f"           about: {about[:80]}")

# B. 机械路径（无 AI 接线，_understand_query 兜底）
print(f"\n=== B. 机械路径 (keywords=None) ===")
rb = m.query_anchors(Q, top_k=3)
for pkg, title, about, loc, score in rb:
    print(f"  [{score:.3f}] {pkg}  |  {title}")

# C. 域外查询 + AI keywords → 验证 entity_gate 路径（ai_mode=True）不死锁
Q2 = "鲁迅的《故乡》里闰土讲了什么"
AI_KW2 = ["鲁迅", "故乡", "闰土"]
print(f"\n=== C. 域外查询 + AI keywords (验证拒答闸) ===")
rc = m.query_anchors(Q2, top_k=3, keywords=AI_KW2)
print(f"  命中数={len(rc)}")
for pkg, title, about, loc, score in rc:
    print(f"  [{score:.3f}] {pkg}  |  {title}")
