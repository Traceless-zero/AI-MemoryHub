---
name: aift-sandbox-refactor
description: FunctionFlow 沙箱工作流 · 文件级改动闭环。当用户要求"复制代码文件到工作区/沙箱里改"、"画布改动落到副本"、"改好了合并回原文件"时使用。核心合同：沙箱副本是唯一编辑区，原文件在回归确认前只读；manifest 是原路径 ↔ 沙箱路径的唯一映射权威。触发词：沙箱、工作区、复制文件改、改动回归、合并回原文件、ff_workspace。
---

# FunctionFlow 沙箱工作流 · 文件级改动闭环

## 合同（已敲定，不要重新解释）
- 工作区副本是**唯一编辑区**；原文件在回归（merge）确认前**只读**，严禁任何写入。
- `ff_workspace/manifest.json` 是映射权威：原路径 ↔ 沙箱路径 ↔ 状态（draft / ready_to_merge / merged）。无 manifest 条目的文件不参与本工作流。
- 代码改动的语义依据是 `functionflow/v1` 的 to-be JSON（画布编排产物）；JSON → diff 的生成由 `aift-refactor-diff` skill 承担，本 skill 只管**文件从哪来、改动落在哪、何时回归**。
- 副本内保持原项目的相对路径结构，回归时按 manifest 一对一写回。
- 副本没有备份/回滚层：改错就**重新从原文件复制覆盖**（即重置），manifest 不变；原文件在回归前始终是干净的参照物。
- 验证职责在本 skill：结构验证与行为验证（见下）都**不需要把沙箱文件放回原位**。

## 工作区结构

`ff_workspace/` 是**默认的 JSON + 代码副本工作与存储区**，每单业务（订单）一个目录，目录内分 scripts/ 与 json/：

```
ff_workspace/
├── manifest.json              # 映射与状态权威（原路径 ↔ 副本路径 ↔ 状态）
└── <订单>/                    # 一单业务一个目录（如 orders）
    ├── scripts/               # 该单的代码副本（唯一可编辑区）
    └── json/                  # 该单的全部 JSON（工作产物 ff_ws- 前缀；样例 functionflow- 前缀）
```

- manifest 为映射权威：`entries[].sandbox` 指向 `ff_workspace/<订单>/scripts/...`；无 manifest 条目的文件不参与本工作流。
- 新 JSON（提取产物 / to-be / after）一律落该订单的 `json/` 子目录；工作产物用 `ff_ws-` 前缀，与 `functionflow-` 样例区分。

## 执行流程

1. **建仓**：复述待复制文件清单，等用户确认 → 建 `ff_workspace/<订单>/scripts/`（订单名与业务相关，如 orders）→ 代码副本复制进去 → 写 manifest（status: draft）。
2. **映射**：对副本跑 `extract_flow*.py` → JSON 落该订单的 `json/` 子目录（文件名 = 图层名）→ 用户导入画布（开新图层，原图层不受影响）。
3. **改动循环**（可多轮）：画布导出 to-be JSON → 交 `aift-refactor-diff` 阅读理解并给收敛方案 → 用户同意方案后由其把改动**写入副本文件**（写入范围 = manifest 映射的工作区路径，原文件不动）→ 可重新提取 JSON 刷新图层对照。每轮结束 manifest 状态保持 draft。

### 验证（不需要把文件放回原位）
- **结构验证**（零执行）：对副本重跑提取器 → 新 JSON 与 to-be JSON 对照，差集 == 画布意图即改动正确。
- **行为验证**（遮蔽运行）：`PYTHONPATH="<沙箱绝对路径><分隔符><项目根绝对路径>"`（Windows 分隔符 `;`）且**必须避免 CWD 抢先**——从项目根直接 `python <入口>` 时 `sys.path[0]=''`（CWD）排在 PYTHONPATH 之前，原文件永远先命中，遮蔽失效（2026-09-03 实测踩坑）。两种可靠姿势：
  ① 从中性目录跑：`cd ff_workspace/<订单> && PYTHONPATH="<abs scripts>;<abs 项目根>" python <入口>`；
  ② Python ≥3.11 用 `-P` 去 CWD 前置：`PYTHONPATH="ff_workspace/<订单>/scripts;<abs 项目根>" python -P <入口>`。
  import 时改过的模块命中工作区副本，未复制的模块经 namespace 包合并自动回落原项目路径；原文件全程未动，跑完无需还原。注意：存在 `__init__.py` 的常规包会整包遮蔽，沙箱需带全包链或项目为 namespace 包。
- 兜底：遮蔽确实跑不通的项目结构，才考虑临时换入换出（swap 后立即还原），不作为默认流程。
- 沙箱（sandbox）一词在文档历史版本中即指 `<订单>/scripts/` 副本区，含义不变。
4. **验收**：展示 副本 vs 原文件 的 unified diff + 受影响函数新行号表；用户确认后进入回归。
5. **回归**：副本内容写回原路径 → manifest 状态改 merged → 回报"哪些文件已回归、哪些仍在草稿"。

## 红线
- 严禁在回归确认前写入原文件（包括"顺手修复""格式化"）。
- 严禁静默覆盖：回归前必须完整展示 diff 并获用户显式确认。
- 严禁改动 `ff_workspace/` 与 manifest 指定路径之外的任何文件。
- 项目根不设 json/ 与 src/；一切工作产物都在 `ff_workspace/<订单>/` 内。
