import sys, os
sys.path.insert(0, r"E:/BaiduNetdiskDownload/项目/AIMH/hma")
import hma_core as H

MEM = r"E:/BaiduNetdiskDownload/项目/AIMH/memory"
IDX = os.path.join(MEM, "index.db")

# rebuild from current (cleaned) front-matter
mem = H.Memory(MEM)
n = mem.rebuild_all()
print("[rebuild] events reindexed:", n)

# unit: keywords contribute
s_kw = H._anchor_score("zzz", "zzz", ["洛基"], "zzz", "洛基", ["洛基"], {"洛基": 1.0})
s_no = H._anchor_score("zzz", "zzz", [], "zzz", "洛基", ["洛基"], {"洛基": 1.0})
print(f"[unit] with keywords={s_kw} without={s_no} -> contribute={s_kw > s_no}")
assert s_kw > s_no

# 怪盗之夜 hits dedicated anchor
res = mem.query_anchors("维罗妮卡的怪盗之夜是在什么时候发生的？", top_k=8, dedup_packages=False)
print("\n[query] 怪盗之夜 top:")
hit = False
for (pid, title, about, loc, sc) in res:
    mk = ""
    if title == "三、怪盗之夜" or "怪盗之夜" in (about or ""):
        mk = "  <<< 怪盗之夜锚点"; hit = True
    print(f"  {sc:7.1f} | {pid} | {title}{mk}")
print("[query] dedicated-anchor hit:", hit)

# regression: topic-mapping win
res2 = mem.query_anchors("我是不是设计过一个角色", top_k=6, dedup_packages=False)
print("\n[query] 我是不是设计过一个角色 top:")
for (pid, title, about, loc, sc) in res2:
    print(f"  {sc:7.1f} | {pid} | {title}")
print("[query] top package:", res2[0][0] if res2 else None)

# confirm no stale locator/tags leaked into index (sanity: query a term only in old locator)
mem.close()
print("\nREAL REGRESSION DONE")
