---
name: aimh-daylog-archive
description: >
  AIMH 的「daylog 写入与派生」技能。daylog 是唯一事件流权威源：当天发生的事（决策/改动/踩坑/讨论经过）
  详实内容只写进当天 daylog，AI 永远只 append、零路由判断；按主题浏览由脚本扫 beat 标记机械派生
  （各包开发日志.md + 日志/主题索引.md），同一标签跨 ≥3 天出现时给出起包建议。命中即加载：
  - 关键词：记 daylog、追加日志、写日志、今天干了啥、daylog beat、派生主题视图、更新主题索引、起包建议
  - 口语化：「记一下今天干的」「把这件事记进日志」「跑一下派生」「看看主题索引」
  - 凡要往 daylog 追加记录、或要刷新主题视图/查起包建议时加载。
---

# AIMH Daylog（写入与派生）

## Overview
daylog 是 AIMH 的唯一**事件流权威源**（`memory/日志/daylog-YYYY-MM-DD.md`，一天一份）。设计定稿见
`memory/项目/AIMH-design-journal/daylog设计.md`。两条铁律：
1. **AI 写入零路由**：对日志永远只做一件事——向当天 daylog 追加一条 beat。不做"归到哪个项目/模块"的判断。
2. **主题视图全部派生**：按主题浏览靠脚本聚合 beat 标记，派生物随时可重建、禁止手改。

## 双轨判据（先过这道二分再动笔）
- **事件**（发生过的事：拍板/踩坑/讨论经过）→ 写进当天 daylog，写完冻结、只增不改。
- **作品**（会被改写的东西：随笔/档案/规范/约定）→ 走 `aimh-ingest` / `aimh-intake` 收进主题包（活文档）；
  daylog 里只留一条 beat `linked` 指过去。
- 判据一句话：这条内容是"发生过的事"还是"会被改写的作品"？

## 写入：scripts/core/daylog_append.py
```bash
python scripts/core/daylog_append.py --title "一句标题" \
    --touched "hma/server.py,项目/AIMH/SCHEMA" \
    --linked "项目/AIMH/开发日志" --tags "读取链路,MCP" \
    --body "正文……"            # 或 --body-file / stdin
# 可选：--date 2026-08-15（默认今天）、--time 21:30（默认当前时间）
```
职责切分：
- **AI 给**：标题、正文、`touched`（本次实际碰的文件，事实观察）、`linked`/`tags`（写入时顺手打标，可为空）。
- **脚本给**：daylog 文件创建（含 FM-V2 骨架）、`## 流水` 节、beat 序号自增（`### NN`）、时间戳、
  touched 存在性校验（不存在仅告警）、`<!--beat ...-->` 注释拼装、`pkage_updated` 刷新。

beat 块形态：
```
### NN · 一句标题 · HH:MM
- touched: [路径1, 路径2]
正文（事实/决策/改动，详写）
<!--beat linked:包/文件 tags:词1,词2-->
```
daylog 特例：front-matter `event_date` 填当天日期（区别于概念文档的 `"—"`）。

## 派生：scripts/core/derive_topic_views.py
纯正则零 AI，挂进 `rebuild_index.py` 管线（「一键更新记忆索引.exe」顺带完成），也可单独跑：
```bash
python scripts/core/derive_topic_views.py
```
- 扫全部 daylog 的 beat → 按 `linked` 聚合重新生成目标包的 `开发日志.md`（每条一行摘要 + `daylog-YYYY-MM-DD#NN` 回跳）；
- 生成全局 `memory/日志/主题索引.md`（按标签/链接双维聚合）；
- **起包建议**：同一标签在 ≥3 个不同日期出现 → 主题索引顶部列出建议。建议由脚本给，决定由用户做。
- **安全闸**：只重写「不存在」或「首部含派生标记」的文件；手写文件（无标记）一律跳过并告警，绝不覆盖。

## 起包流程（唯一保留的路由判断，显式确认）
1. 主题索引出现起包建议（或用户直接说"把 X 收一下"）。
2. 与用户确认落点 → 走 `aimh-intake` 判型建新包，内容策展成作品的权威副本。
3. 当天 daylog 记一条起包 beat（`linked` 指新包）。旧条目不回搬——过程记录留在 daylog，召回与文件位置无关。
4. 此后该主题新 beat 的 `linked` 改指新包，派生视图自动聚合新旧。

## 纪律
- 详实内容只写 daylog 一处；`开发日志.md` 是派生视图，**永不手写**。
- 不动派生物（开发日志.md / 主题索引.md）——要改就改 daylog 的 beat 然后重跑派生。
- 一次性内容永久留 daylog，不为了"整齐"而搬家。

## Reference
- 设计定稿：`memory/项目/AIMH-design-journal/daylog设计.md`
- 写入脚本：`scripts/core/daylog_append.py`；派生脚本：`scripts/core/derive_topic_views.py`
- 作品收录：`aimh-ingest` / `aimh-intake`（与 daylog 事件流正交）
