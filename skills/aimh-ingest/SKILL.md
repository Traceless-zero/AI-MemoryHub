---
name: aimh-ingest
description: >
  把通用文本 / 笔记 / 日志 / 文章 / 资料 / 想法存入 HMA（Hybrid Memory Architecture）
  长期记忆时，本技能定义「Agent 即理解层」的零成本收录流程。三分支：
  通用（本文件）/ 文章·资料（references/branch-paper.md，产 orig+review 一对）/
  对话记录（references/branch-dialog.md，产逐字+拍板单包）。
  何时用（命中即加载）：记一下、存进记忆、收录这段、存个笔记、记住这个、写进记忆、
  HMA、长期记忆、ingest、note、整理成记忆、论文、文章、文献、综述、归档这篇、
  读懂这篇、对话、会议、访谈、对话记录、把这场会存一下；
  凡用户给一段非角色类文本、要求存入 HMA 记忆库时，先加载本技能。
  注意：内容明显是「角色 / OC 档案」时改加载 oc-dossier（store 分支）。
---

# HMA Ingest（通用收录 · 骨架）

> **权威**：流程细节 `拆包与收录规范.md`（§2 通用收录流程 / §3 拆包触发铁律 / §5 项目收录 / §9 对照表；T21-T23 钉映射）、FM 契约 `SCHEMA.md`（唯一真相源）；召回 ABSTAIN → 停止上报，勿即兴。

## 路由（判断）

- 角色/OC 档案 → `oc-dossier`（store 分支）
- 论文/长文 + 归档理解意图 → 读 `references/branch-paper.md`（产 orig+review 一对）
- 对话/会议逐字 → 读 `references/branch-dialog.md`（单包）
- 其余 → 下方通用流程。**分支流程住在 references/ 里，选中必须读完再动手**（停在本文件硬套 = 流程违规）。

## 通用收录流程（六步）

1. **定位 root**：notes/项目/其他/用户模块（q-2 铁律：用户自身数据进 `memory/用户/<模块>/`）；嵌套按逻辑从属、新建目录**一律中文**（R59）。召回键 `["通用收录流程"]`
2. ⛔ **一次比对 index（硬闸门，不跑完禁落库）**：`python -m hma.engine query <root> "<关键词>"` 一次分出归并候选/关联事件——2026-08-28 血泪：跳过 = 重复碎片包。召回键 `["通用收录流程"]`
3. **理解拆分 + 落点**：按 `references/ingest_prompt.txt` 拆 1+ CEMA 包；FM 11 必填字段（契约唯一真相源 SCHEMA.md §2；**禁写 id/aliases/features/created/updated**）。召回键 `["拆包触发铁律"]`
4. **落库**：推荐 `new_package.py --fill`（fail-closed）或直写 .md + `rebuild_index.py --no-gui`；**勿用 hma.cli write**（丢四要素与 pkage_*）。召回键 `["跨类型拆包对照表"]`
5. **记当日账**：`daylog_append.py`（收尾自动重建索引；流程见 aimh-daylog-archive 骨架）
6. ⛔ **收录钩子（完成标记，唯一纠错出口，绝不能省）**：输出「已收录至 X」+ 相似包（合并触发）/关联/移包开口

## 模块路由（用户 / 项目数据）

用户数据 → `memory/用户/<偏好|方法论|身份锚点|踩坑|事实>/`；项目工程 → `memory/项目/<项目名>/`（README 式：需求清单/项目结构/约定/架构；**结构不装铁律**；开发日志派生）；daylog 只装闲话+大事件简介+linked。召回键 `["项目包体拆包"]`；细则 SCHEMA.md §4。

## 时间描述唤起（读侧）

时间语→ISO（不确定就问）；读经 `hma.daylog` `read_day`/`days_in_range`；细节走 `memory_read_section`。规范：召回消歧管线 §14.6。

## 纪律

长文不压缩（细粒度靠锚点）；确定性归引擎、理解归你；敏感内容不落 memory（工程红线 §4）。
