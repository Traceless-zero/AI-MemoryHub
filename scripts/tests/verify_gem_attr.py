"""验证：圣保罗之焰改属性特征变体后，gem 各 phrasing 仍能召回 veronica-origin。"""
import sys
sys.path.insert(0, r"E:/BaiduNetdiskDownload/项目/AIMH")
from hma.hma_core import Memory

ROOT = r"E:/BaiduNetdiskDownload/项目/AIMH/memory"
m = Memory(ROOT)
print("== rebuild index ==")
n = m.rebuild()
print("rebuilt events:", n)

GEM = ["黄蓝色的宝石", "蓝钻", "深海蓝橙焰钻石", "那颗钻石", "价值连城的宝石", "圣保罗之焰"]
print("\n== query()(四要素+正文) top1 ==")
for q in GEM:
    r = m.query(q, top_k=2)
    print(f"  [q={q!r}] -> {[x[0] for x in r[:2]]}")

print("\n== query_anchors(allow_abstain=False) top1 pkg ==")
for q in GEM:
    r = m.query_anchors(q, top_k=1, allow_abstain=False)
    print(f"  [q={q!r}] -> {r[0][0] if r else None} | {r[0][1][:16] if r else ''}")

print("\n== query_features(L1.5 属性特征归一) ==")
for q in GEM:
    print(f"  [q={q!r}] -> {m.query_features(q, top_k=1)}")
