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

# AIMH Daylog（写入与派生 · 骨架）

> **权威全文**：`memory/项目/AIMH-design-journal/daylog设计.md`（映射由回归 T17-T20 钉住）。
> **执行规则**：每步按召回键调 `mcp__aimh__memory_query_anchors`（`allow_abstain=true`），按命中锚点执行；
> **召回 ABSTAIN → 本步停止并报告，勿即兴补流程**。

1. **判记账范围**：这条内容是"发生过的事"（→ daylog）还是"会被改写的作品"（→ aimh-ingest/intake）？
   召回键：`["双轨判据"]`
2. **写入**：`python scripts/core/daylog_append.py`——fail-closed：`--anchor-about` / `--anchor-keywords` /
   新建 `--summary` / `--body` 缺一即拒；收尾自动重建索引（红线5 机制化）。
   召回键：`["写入协议"]`
3. **派生**：`python scripts/core/derive_topic_views.py`（已挂 rebuild 管线；派生物**永不手改**）。
   召回键：`["派生视图", "主题索引"]`
4. **起包**（唯一路由判断，须用户确认）：主题索引建议 → `aimh-intake` 判型建包 → 当天记起包 beat。
   召回键：`["起包规则"]`
