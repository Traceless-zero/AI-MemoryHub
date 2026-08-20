---
name: aimh-recall-test
description: >
  HMA 读取侧召回编排技能（TEST 版·沙箱）。把"三级询问精度→返回粒度映射"与"features 三流路由"
  合流为读取侧闭环：AI 先判询问精度（模糊/中等/精确），再路由（features 两跳归一 / 主题 / 混合），
  按精度选返回粒度（L1 名称 / L2 摘要 / L3 正文），最后从 index.db+front-matter 的清水组合回复。
  精度判定与近义推理交 AI（理解层），引擎只交结构化原语。本文件为测试版，原始 aimh-recall 已保留未动。
---

# HMA 读取侧召回编排（aimh-recall-test · 沙箱测试版）

> 设计来源：2026-08-10 定稿的读取流程——两根正交轴：
> - **精度轴**：询问精度 → 返回粒度（L1 名称 / L2 摘要 / L3 正文），由 AI 判精度，不另建零-ML 选择器。
> - **路由轴**：features 两跳归一（Flow A 子实体）→ 主题（Flow B 整篇）→ 混合（Flow C）。
> 引擎只交付粒度原语与路由结果，语义判断 + 回复组合交 AI。

## 测试环境（TEST ONLY — 生产改真实路径）
- 仓库根 `<repo>`：运行 `python <repo>/scripts/core/where.py --json` 取 `repo` 字段（或读 `~/.hma_home` 指针文件）。**不要写死绝对路径**。
- 沙箱引擎：`<repo>/test_anchor_slim/hma_core.py`（含 browse_by_date/summarize/elaborate/disclose/query_two_hop/retrieve）
- 沙箱记忆根：`<repo>/test_anchor_slim/skilltest_iso/memory`（已预置 3 包：project-alpha / project-beta / veronica-note，独立 index.db 隔离）
- 真实路径对照：`<repo>/hma/hma_core.py` + `<repo>/memory/`（生产用，本 TEST 版跑沙箱）

## 读路径编排（AI 按此执行）

对每条用户询问 q：

1. **判精度**（AI 理解层，零-ML 不介入）：
   - 模糊（只给时间范围/无具体指向，如"半年前我做过什么"）→ 走 **L1**。
   - 中等（指向某包但求提醒，如"那个项目是干什么来着"）→ 走 **L2**。
   - 精确/求细节（点名实体或要具体内容，如"黄蓝色宝石""更具体的呢"）→ 走 **L3** + 路由。

2. **路由**（仅当询问指向具体内容/实体时）：
   - 含变体/属性词（颜色、材质、代号…）→ `query_two_hop(q)` 两跳（features 归一→全文）走 Flow A/B/C。
   - 仅主题/时间 → `browse_by_date` 或主题信号。

3. **选粒度原语**（按精度）：
   - **L1**：`mem.browse_by_date(start, end)`（默认 by=created 写入时间；可 by="event_date" 内容时间）→ 只回名称列表。
   - **L2**：`mem.summarize(id)` → 只回 summary。
   - **L3**：`mem.elaborate(id)` 或 `mem.disclose(id, depth=3)` → summary + 正文章节。

4. **组合回复**：从取回的 front-matter/index.db 清水字段组织回答；变体/近义判断交 AI
   （如"粉白双色宝石？我倒是记得一个橙蓝双色的宝石"）。

## 等价调用
```python
import sys, os
# <repo> = 仓库根：优先读 ~/.hma_home 指针（where.py 已登记），缺失则手动填——零路径写死
_HOME = os.path.join(os.path.expanduser("~"), ".hma_home")
REPO = open(_HOME, encoding="utf-8").read().strip() if os.path.isfile(_HOME) else input("AIMH 仓库根绝对路径: ").strip()
sys.path.insert(0, os.path.join(REPO, "test_anchor_slim"))
from hma_core import Memory
mem = Memory(os.path.join(REPO, "test_anchor_slim/skilltest_iso/memory"))
# L1 时间浏览
mem.browse_by_date("2026-01-01", "2026-12-31")
# L2 摘要
mem.summarize("project-alpha")
# L3 正文
mem.elaborate("veronica-note")
# 路由+精度：黄蓝色宝石 → Flow A 命中圣保罗之焰，再 L3 取正文
r = mem.retrieve("黄蓝色宝石")   # 路由定位
mem.disclose("veronica-note", depth=3)
```

## 护栏
- 未命中静默放过；私有包按权限不外露。
- 引擎零-ML 只做归一+召回+交载荷；精度判定、近义推理、人格化回复均交 AI。
- 本文件为 TEST 版，原始 `aimh-recall` 已保留未动；验证通过后再决定是否回灌生产 skill。
