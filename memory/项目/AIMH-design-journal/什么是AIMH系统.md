---
title: 什么是AIMH系统
summary: AIMH（AI Memory Hub）是一个零向量、零 ML 的确定性长期记忆系统——写入时由 AI 充当理解层把混沌信息（口语、别名、重复）规范成结构化记忆包，读取时只需最小必要性理解即可精准召回。它自上而下分四层（存储/引擎/接口/理解），以 CEMA 闭环（理解→规范→落库→召回）与四要素（person/event_date/location/topic）+ 锚点模型承载细粒度召回，三级漏斗 L1→L2→L3 把查询路由到正确粒度，字段加权与 dK 分差裁切把 gold 压入 top-5。当前为零依赖原型，LoCoMo 1540 recall@30≈99.5%、拒答层已随 V1.0 落地。
tags: [ aimh, architecture, 设计理念, 项目结构, overview, 四要素, CEMA, rerank, AIMH ]
linked: [ SCHEMA, 用户操作手册, 工具与技能总览 ]
person: []
event_date: —
location: []
topic: [{"AIMH总览": ["四层架构", "CEMA", "三级漏斗", "四要素"]}]
anchors:
  - Chapter: "一、核心隐喻：把\"泥沼\"变\"清水\""
    about: "记忆系统的根本矛盾是：写入时信息混沌（口语、别名、重复、矛盾），读取时又要精准。"
    keywords: ["记忆系统"]
  - Chapter: "二、四层架构"
    about: "AIMH 自上而下四层，写入沿箭头向下、读取沿箭头向上："
    keywords: ["自上而下"]
  - Chapter: "三、CEMA 循环：AI 理解 + 确定性写入"
    about: "AIMH 是事件驱动的确定性记忆架构（CEMA）：AI 理解 + 引擎确定性写入，CEMA = 把\"模糊输入\"变成\"结构化记忆包\"的闭环；前台薄索引 + 后台正文冷存储，活文档整合、无状态检索，理解归 AI、写入归引擎。"
    keywords: ["模糊输入", "CEMA", "铁律", "前后台", "无状态", "事件驱动", "记忆架构", "活文档", "理解归AI"]
  - Chapter: "四、四要素：person / event_date / location / topic"
    about: "一等字段，必填非死重——有对应内容就填，留空=漏召回："
    keywords: ["必填非死重"]
  - Chapter: "五、锚点模型"
    about: "锚点是\"一个包 + 多子事件\"的细粒度召回单元，唯一形态 `{Chapter, about, keywords}`："
    keywords: ["多子事件"]
  - Chapter: "六、三级召回漏斗 L1→L2→L3"
    about: "- L1（包级）`query`：BM25 在 front-matter 上做包级召回，缩圈到候选包。"
    keywords: ["上做包级"]
  - Chapter: "七、裁切与字段加权"
    about: "- 字段加权：读取时按四要素命中数调序（`person4>time3>loc2>topic1`），命中要素越多越靠前、永不清退。"
    keywords: ["字段加权"]
  - Chapter: "八、拒答层（已落地 · V1.0）"
    about: "引擎内置拒答闸（_abstain 四道闸 + corpus_missing_entity 反相硬闸），域外/无依据查询如实返回「我不知道」，对抗样本诚实拒答。"
    keywords: ["引擎内置"]
  - Chapter: "九、项目结构与当前状态"
    about: "项目结构与当前状态：仓库根 memory/+hma/+scripts/core/+一键更新记忆索引.exe；基准 LoCoMo 1540 题 recall@30≈99.5%、hit@5 89.7–92%，拒答层已随 V1.0 落地，零依赖原型。"
    keywords: ["确定性脚本", "LoCoMo", "recall@30", "基准", "当前状态"]
pkage_created: 2026-07-26
pkage_updated: 2026-08-29
---

# 什么是 AIMH 系统

> 本文是 AIMH（AI Memory Hub）的总览：它要解决什么问题、核心设计哲学是什么、四层架构怎么分层、CEMA 循环如何把"理解"与"写入"解耦、四要素与锚点模型怎么承载细粒度召回、三级漏斗（L1→L2→L3）怎么工作、裁切与字段加权如何把 gold 压进 top-5，以及项目当前状态。

## 一、核心隐喻：把"泥沼"变"清水"

记忆系统的根本矛盾是：写入时信息混沌（口语、别名、重复、矛盾），读取时又要精准。

AIMH 的解法是**写入时把泥沼搅成清水**：
- 写入侧由 AI 充当理解层，做**实体消歧、规范命名、结构化**——同一概念的不同说法（如"回旋镖""回旋镖计划"）在写入时就归一；
- 召回时世界已经清澈，检索只需做**最小必要性的理解**，无需在读取时重新推断。

理解力前置到写入时，读取侧因此极轻——这是 AIMH 能在零向量、零 ML 前提下拿到高召回的根。

## 二、四层架构

AIMH 自上而下四层，写入沿箭头向下、读取沿箭头向上：

1. **存储层**：`memory/*.md`（权威源，人类可读可编辑）+ `index.db`（薄索引，可由 .md 的 front-matter 全量重建）。
2. **引擎层**：`hma/hma_core.py`——确定性的索引、查询、锚点派生、装卸。零依赖、零 ML。
3. **接口层**：`hma.cli` / `hma.engine`（命令行）、`hma/server.py`（MCP server，暴露 11 个工具）、`scripts/core/*`（确定性脚本）。
4. **理解层**：当前对话的 Agent（你）+ `aimh-*` 技能 + LLM 适配器——只做"理解"，落库、建索引、装卸全部交给确定性脚本。

> CEMA 铁律：AI 只负责理解，脚本确定性写入。`.md` 是权威、永不丢弃；`index.db` 是可重建的薄缓存。

## 三、CEMA 循环：AI 理解 + 确定性写入

CEMA（Cognitive Event-driven Memory Architecture，认知-事件驱动记忆架构） = 一个把"模糊输入"变成"结构化记忆包"的闭环：

- **C（Capture/理解）**：Agent 把文本/对话/文章拆成"凝聚性事件包"，生成元数据、发现关联。
- **E（Encode/规范）**：统一 front-matter 契约（SCHEMA.md 为唯一权威），四要素归一，变体数组替代独立 aliases/features。
- **M（Memory/落库）**：`Memory.write()` 原子写 `.md` + upsert 索引；`index.db` 可随时 `rebuild`。
- **A（Activate/召回）**：三级漏斗把查询路由到正确粒度。

关键：理解在 C/E 由 AI 完成，M/A 是确定性脚本——可调试、可重建、不靠模型运气。

## 四、四要素：person / event_date / location / topic

一等字段，必填非死重——**有对应内容就填，留空=漏召回**：

- `person`：涉及的人物/角色/组织（变体数组，规范名+别名）。
- `event_date`：事件时间。无独立故事时间写哨兵串 `"—"`（仍标量，召回不注入时间信号）；单点 `YYYY-MM-DD` / 区间 `YYYY-YYYY` 照常。
- `location`：地点。
- `topic`：主题词。

写入侧落盘为 `[{规范名:[变体]}]` 的 dict；引擎内合并，读取时按命中要素数（`person4 > time3 > loc2 > topic1`）调序、永不清退。

## 五、锚点模型

锚点是"一个包 + 多子事件"的细粒度召回单元，唯一形态 `{Chapter, about, keywords}`：

- `Chapter`：正文定位键（**无独立 locator 字段**），即 `##`~`######` 标题原文。
- `about`：该节要点梗概（参与锚点匹配、可直答"这章讲什么"）。
- `keywords`：章级精准命中词（规范名/精确名/章级事件年份）。

`derive_anchors(md, max_level=6)` 确定性派生（写入侧细切 `##`~`######` 全层级）。写入时补 `about` 与 `keywords` 可大幅提升召回；关键词须覆盖 时间/地点/关键事件/锚定物品/人物 五维各 ≥1 token。

## 六、三级召回漏斗 L1→L2→L3

- **L1（包级）`query`**：BM25 在 front-matter 上做包级召回，缩圈到候选包。
- **L2（章级）`query_anchors`**：在命中包的 anchors 上做关键词匹配，定位到具体章（扁平 BM25，无独立选章子系统）。
- **L3（正文级）`memory_read_section`**：取某章正文，交给 READ/REFINE 做最终验证与重排。

F+C+A+READ 三段式：F-stage 子串变体归一如"回旋镖"⊂"回旋镖计划"缩圈；C+A 消歧；READ 取 topK 正文。REFINE 常识桥接（如"最值钱→宝石"）为设计稿未接引擎；包级 rerank 装置默认关，当前生效的是确定性裁切与字段加权。

## 七、裁切与字段加权

- **字段加权**：读取时按四要素命中数调序（`person4>time3>loc2>topic1`），命中要素越多越靠前、永不清退。
- **dK 分差裁切**：`waterfall_cut` 锚点级相邻分差 >75 单向裁切收束候选，不误杀（50 vs 75 对比已跑，维持 75）。
- **rerank 装置**：包级 BM25 rerank 保留但默认关（`rerank=False`），重开前必须先改成锚点级；「自以为是层」（rule#1 / OR-fail-safe 保 gold 逻辑）已全删，绝不重写回 core。
- 目标：把 gold 压入 top-5，对齐 TrueMemory 93% 基线。

## 八、拒答层（已落地 · V1.0）

引擎 `query_anchors` / `resolve_query` 内置拒答闸（`_abstain` 多道闸：空池 / 语料包含性 / 覆盖不足 / 越界 / 零重叠 → 如实返回「我不知道」；叠加 `corpus_missing_entity` 反相硬闸：所有判别实体在语料都查不到即拒答），`multihop` 扩簇复用同套。MCP `memory_query_anchors` / `memory_resolve` 默认 `allow_abstain=True`，并支持传 `keywords`（AI 解析的复合实体词）触发 `corpus_missing_entity` 硬闸。对抗样本不再硬凑章节，而是诚实拒答。该层已于 2026-08-15 随 V1.0 落地（Demo mini-bench 可答 20/20；对抗 4/5——某文学名著类域外题机械路径漏拒为已知边界，AI 接口路径 5/5 硬拒）。

## 九、项目结构与当前状态

- 仓库根：`memory/`（事件包）+ `hma/`（引擎）+ `scripts/core/`（确定性脚本）+ `skills/`（可插拔客户端技能）+ `一键更新记忆索引.exe`（双击全量重建）。
- 当前状态：零依赖原型；LoCoMo 1540 recall@30≈99.5% / hit@5 89.7–92%；拒答层已随 V1.0 落地。
- **两级召回（query() 锁包 → scoped query_anchors）规模压测（2026-08-29 重建基准，原 2026-08-19 脚本失传、复现链断裂）**：1161 事件强干扰库（52 真实包 + 423 干扰包，泛词组合树 + 每 gold 5 个近名干扰（「战争与和平·卷一/卷二」形态：共享家族前缀、规范键互异且不含 gold 实体全串、各有泛词判别字段））、16 gold 确定性抽样（seed=20260829）、AI 流实体抽取查询（topic+person 规范名，cap 3）：两级 recall@5 **100%** vs 全局 unscoped **100%**（误拒均 0；均耗时 118ms / 22ms）。**1 例未召回（daylog设计 两级@6 / 全局@1）根因已实证修正**：该包 FM topic 四要素漏填（「漏填=漏召回」的活例），判别词全在锚点而 L1 包级打分不含锚点词，仅剩 rid/title 子串分（192/词），被 topic 规范名恰为「设计」的干扰包（EXACT 198/词）压过。沙箱补 topic 验证：gold 跳至 rank 1（468 vs 396），两级路径恢复；生产已同款修复。**我此前写入的「派生视图占据 L1」假设被证伪**——occupier 实为泛词池撞上「设计」的合法干扰包；自省：先写假设后验证违反 §九「归因必须真 trace」，此教训对 AI 自己同样适用。前几轮失败（超字符串同分 3 例、标签污染 1 例）已分别随家族前缀形态与 daylog 对齐消除。另：daylog-2026-08-13 实体即标题却曾未召回，经三轮修正（双 ID 空间错配→克隆回声→规范键重复）定位为生成器缺陷叠加，最终消除。最终（daylog设计 FM 治理后）：**两级与全局均为 100%@5**；两级@1 = 100% 反超全局 93.8%（topic 别名 EXACT 通道的直答优势）。「先锁包再精检」与全局锚点级在本库规模下打平，优劣需在更大规模/更强干扰下继续观察。过程教训：基准迭代四轮各揪出一类生成器缺陷（双 ID 空间→克隆回声→规范键重复→字段不对称），用户的两次质疑各纠正一轮。复现入口 `python scripts/tests/bench_aimh_internal_groups.py`（确定性 seed，TEMP 沙箱不落生产）。
- 设计期刊（本目录）是架构的唯一真相源；SCHEMA.md 为 front-matter 契约的唯一权威。
