---
title: FunctionFlow functionflow/v1 JSON 合同钉死：蓝图结构 + 改动说明
summary: FunctionFlow 导出的 functionflow/v1 JSON 用途已被固定为「蓝图结构(to-be) + 改动说明(intent)」，不是当前代码的镜面快照。蓝图结构描述代码应长成什么样(目标数据流)；intent 是人工在画布编排后写入的意图层(用函数名锚定节点)。一份 JSON 两种用途：导入回画布还原图、交给 AI 照蓝图改源码。
tags: [ functionflow/v1, JSON合同, 蓝图结构, 改动说明, AI改码闭环 ]
linked: [ 项目/FunctionFlow/FunctionFlow-约定, 项目/FunctionFlow/FunctionFlow-架构 ]
person: []
event_date: 2026-09-03
location: []
topic: [{"FunctionFlow": ["functionflow", "代码可视化"]}, {"schema合同": ["JSON用途", "to-be蓝图"]}]
anchors:
  - Chapter: "用途钉死：蓝图结构 + 改动说明"
    about: "JSON 不是现状镜面，而是 to-be 蓝图 + 人工 intent 改动说明，消除 AI 模糊空间。"
    keywords: ["2026-09-03", "FunctionFlow", "合同钉死", "functionflow/v1 JSON", "GLM5.3flash"]
  - Chapter: "蓝图结构(to-be) 与 intent 改动层"
    about: "节点/边描述代码应长成什么样；intent 用引号内函数名锚定节点，机械提取不产。"
    keywords: ["2026-09-03", "FunctionFlow", "to-be蓝图", "intent字段", "函数名锚定"]
  - Chapter: "一份 JSON 两种用途"
    about: "① 导入回 FunctionFlow 还原可视化图(蓝图)；② 交给 AI 照蓝图改源码(忽略 position)。"
    keywords: ["2026-09-03", "FunctionFlow", "双向契约", "AI改码闭环", "还原画布"]
  - Chapter: "本次已落实的改动"
    about: "src/types.ts 的 schema doc 与 FunctionFlowFile 接口加 intent?: string；refactor-diff skill 复制进项目 .workbuddy/skills。"
    keywords: ["2026-09-03", "FunctionFlow", "intent字段落地", "types.ts", "skill入项目"]
pkage_created: 2026-09-03
pkage_updated: 2026-09-03
---

# FunctionFlow functionflow/v1 JSON 合同钉死：蓝图结构 + 改动说明

## 用途钉死：蓝图结构 + 改动说明

FunctionFlow 导出的 `functionflow/v1` JSON，用途已被固定为「**蓝图结构（to-be）+ 改动说明（intent）**」——**不是**当前代码的镜面快照。

- 过去模糊点：AI 分不清 JSON 是「现状描述」还是「目标声明」，导致照图改码时方向错乱。
- 钉死来源：GLM5.3flash 建议把 JSON 用途说明固定下来，一句话说清「蓝图结构 + 改动说明」，消除 AI 的模糊空间。
- skill 侧已对齐：`functionflow-refactor-diff` 描述为「画布 = 目标数据流声明（to-be），intent 字段 = 注脚」。

## 蓝图结构（to-be）与 intent 改动层

- **蓝图结构（to-be）**：节点 / 边描述代码「**应该长成什么样**」（目标数据流），而非现状。
- **改动说明（intent）**：人工在画布编排后写入的**意图层**；句中用**引号包裹的函数名**锚定节点（如「把 `extract_flow` 的输出接到 `render` 前」）。
- 该字段**机械提取不产**——只有人在画布上编排后才出现；它是对 AI 的「注脚」，不是结构定义。

## 一份 JSON 两种用途

同一份 JSON，两种消费方式，互不冲突：

1. **导入回 FunctionFlow**：还原可视化图（蓝图本身）。
2. **交给 AI 改源码**：AI 照着蓝图去改真实代码，**直接忽略 `position` 等布局字段**即可。

这就是 FunctionFlow 区别于纯「代码理解/调用图」竞品的核心闭环——图不是给人读的，是给 AI 当 to-be 合同去执行的。

## 本次已落实的改动

- `src/types.ts` 的 schema doc 已改写为「蓝图结构 + 改动说明」语义（明确 to-be vs 现状）。
- `FunctionFlowFile` 接口已新增 `intent?: string` 字段（人工改动意图层）。
- `functionflow-refactor-diff` skill 已从 user-level（`~/.workbuddy/skills/`）**复制进项目** `.workbuddy/skills/functionflow-refactor-diff/`，项目自包含。
