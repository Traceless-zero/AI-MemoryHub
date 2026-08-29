# -*- coding: utf-8 -*-
"""生产回归：直接调已改写的 resolve_two_layer，验证示例事件→示例角色 + 全量零误路由 + 「哲学」召回（13 题）。

不进沙箱、读真实 index.db（events 表含 anchors）。
第 13 题「哲学」为 B 方案治本项：锚点 keyword 独立档后，tag 含「哲学」的 随笔/论文 必须进候选。
期望路由（绿基线）：
  示例事件 -> 原创角色/示例角色 (hit)
  示例信物 -> 物品/示例信物 (hit)
  示例角色 -> 原创角色/示例角色
  示例角色 -> 原创角色/示例角色
  唱片 -> 原创角色/示例角色
  布达佩斯 -> dir[示例信物,苍穹之泪,示例角色] (三并列，dK 砍不动)
  示例地点 -> 原创角色/示例角色
  铸造厂 -> 原创角色/示例角色
  示例设定 -> 原创角色/示例角色
  示例别名 -> dir[示例信物,示例角色] (二并列)
  示例协议 -> 原创角色/示例角色
  苍穹之泪 -> 物品/苍穹之泪
"""
import sys
sys.path.insert(0, r"E:/BaiduNetdiskDownload/项目/AIMH")
from hma.hma_core import Memory

MEM = r"E:/BaiduNetdiskDownload/项目/AIMH/memory"

QUERIES = ["示例事件", "示例信物", "示例角色", "示例角色", "唱片",
           "布达佩斯", "示例地点", "铸造厂", "示例设定", "示例别名", "示例协议", "苍穹之泪"]


def pcands(env):
    st = env.get("stage")
    if st == "hit":
        return st, [env["hit"]["package_id"]]
    if st == "dir":
        return st, [d["package_id"] for d in env.get("dirs", [])]
    if st == "file":
        return st, [f["package_id"] for f in env.get("files", [])]
    return st, []


EXPECT = {
    "示例事件": {"原创角色/示例角色"},
    "示例信物": {"物品/示例信物"},
    "示例角色": {"原创角色/示例角色"},
    "示例角色": {"原创角色/示例角色"},
    "唱片": {"原创角色/示例角色"},
    "布达佩斯": {"物品/示例信物", "物品/苍穹之泪", "原创角色/示例角色"},
    "示例地点": {"原创角色/示例角色"},
    "铸造厂": {"原创角色/示例角色"},
    "示例设定": {"原创角色/示例角色"},
    "示例别名": {"物品/示例信物", "原创角色/示例角色"},
    "示例协议": {"原创角色/示例角色"},
    "苍穹之泪": {"物品/苍穹之泪"},
}

if __name__ == "__main__":
    m = Memory(MEM)
    print(f"{'query':<14} | {'结果(stage + 包)':<55} | 解析包集合判定")
    print("-" * 90)
    fails = 0
    for q in QUERIES:
        st, c = pcands(m.resolve_two_layer(q))
        ok = set(c) == EXPECT[q]
        if not ok:
            fails += 1
        flag = "OK" if ok else "FAIL <--"
        print(f"{q:<14} | {st+' '+str(c):<55} | {flag}")
        if not ok:
            print(f"{'':<14} |   期望包集合 {sorted(EXPECT[q])}")
    # 「哲学」回归断言（B 方案治本项）：锚点 keyword 不再蹭 proper-noun 150，
    # 真正 tag 含「哲学」的 存在主义随笔 / 西西弗斯论文 必须进候选集。
    st, c = pcands(m.resolve_two_layer("哲学"))
    ok_essay = any("文章/随笔" in p for p in c)
    ok_paper = any("西西弗斯" in p for p in c)
    ok_phil = ok_essay and ok_paper
    if not ok_phil:
        fails += 1
    print(f"{'哲学':<14} | {st+' '+str(c):<55} | {'OK' if ok_phil else 'FAIL <--'}  (随笔{ok_essay}/论文{ok_paper})")
    m.close()
    print("-" * 90)
    print(f"包路由通过 {13-fails}/13, 失败 {fails}")
    sys.exit(1 if fails else 0)
