import sys, json, os
sys.path.insert(0, r"E:/BaiduNetdiskDownload/项目/AIMH")
from hma.hma_core import Memory

REPO = r"E:/BaiduNetdiskDownload/项目/AIMH/memory"
m = Memory(REPO)

def show(q):
    print(f"\n=== 查询(理解层压词后): {q!r} ===")
    hits = m.query_features(q, top_k=5)
    print("  [F] query_features 命中:")
    for pid, canon, reason, score in hits:
        print(f"      {pid}  canon={canon}  reason={reason}  score={score}")
    a0 = m.query_anchors(q, top_k=3, use_features=False)
    a1 = m.query_anchors(q, top_k=3, use_features=True)
    def fmt(lst):
        return [(pid.split("/")[-1], round(s,1), title) for pid,title,_,_,s in lst]
    print("  [C+A] 纯锚点 top3:", fmt(a0))
    print("  [F+C+A] 启用 features top3:", fmt(a1))
    p0, p1 = {x[0] for x in a0}, {x[0] for x in a1}
    if p0 != p1:
        print(f"  >> F 缩圈: 候选包 {len(p0)} -> {len(p1)}")
    return hits, a1

# 模拟 AI 理解层把自然语言压成关键词（HMA 契约：CJK 整句须先压词）
CASES = {
    "重生计划是谁封存的": "重生计划",
    "武器重构怎么实现的": "武器重构",
    "协议X-2 是谁执行的": "协议X-2",
    "弗瑞锁定的影子特工叫什么": "协议X-2",
    "红房训练出来的特工": "红房",
    "幽影核心是什么": "幽影核心",
}

last = None
for natural, kw in CASES.items():
    print(f"\n--- 自然语言: {natural}  (压词 -> {kw}) ---")
    last = show(kw)

# READ 段抽样
print("\n=== READ 段抽样（武器重构）===")
hits, a1 = show("武器重构")
if a1:
    pid, title, summ, loc, s = a1[0]
    target = None
    for dp,_,fs in os.walk(REPO):
        for f in fs:
            if f.endswith(".md") and pid in os.path.join(dp,f).replace("\\","/"):
                target = os.path.join(dp,f)
    if target:
        txt = open(target, encoding="utf-8").read()
        idx = txt.find(loc)
        snip = txt[idx:idx+200].replace("\n"," ") if idx>=0 else "(locator未找到)"
        print(f"  READ {os.path.basename(target)} / locator={loc!r}")
        print("  正文片段:", snip[:180])
m.close()
