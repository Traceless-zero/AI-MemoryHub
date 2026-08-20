"""一次性修复 veronica-origin.md 的 front-matter 格式回归。

回归来源：scripts/tests/fix_veronica_four_element.py 用 json.dumps(pkg.anchors)
把 anchors 写成单行，并用正则换字段，破坏了 v3 多行 block 格式并污染 event_date。

本脚本用引擎正规序列化器 to_markdown 回写，保证：
  1) 描述表达式回到用户原话斜杠式：圣保罗之焰:["黄/橙","蓝","双色","宝石","价值连城"]
     —— _feat_alt_match(hma_core.py:84) 对含 '/' 的变体做 f.split('/') OR 匹配（黄 或 橙）。
  2) event_date 回到 FM-V2 哨兵 "—"（OC 背景，无独立故事/事件时间），
     不是 pkage_created 的数字复制。
  3) anchors 经 to_markdown -> _fmt_anchors_block 写成多行 v3 block。
"""
import sys

REPO = r"E:/BaiduNetdiskDownload/项目/AIMH"
sys.path.insert(0, REPO)

from hma.hma_core import EventPackage

FP = r"E:/BaiduNetdiskDownload/项目/AIMH/memory/原创角色/维罗妮卡·夏·雪莱/veronica-origin.md"

# 1) 读取（单行 anchors / 逗号 split 的 topic 解析均无损）
pkg = EventPackage.from_markdown(open(FP, encoding="utf-8").read(), filepath=FP)

# 2) 描述表达式：用户原话斜杠式（黄/橙 是含 '/' 的单一变体 token）
pkg.topic = [
    {"圣保罗之焰": ["黄/橙", "蓝", "双色", "宝石", "价值连城"]},
    {"幽影核心": ["外星遗骸", "外星技术碎片"]},
    {"协议X-2": ["X-2", "X合同"]},
    {"回旋镖": ["回旋镖计划"]},
]

# 3) event_date 回到 FM-V2 哨兵（OC 背景无独立故事/事件时间；非 created 复制）
pkg.event_date = "—"

# 4) 规范回写：anchors 多行 v3 block，其余字段归一
open(FP, "w", encoding="utf-8").write(pkg.to_markdown())
print("OK: 多行 anchors + event_date='—' + 圣保罗之焰=['黄/橙','蓝','双色','宝石','价值连城']")
