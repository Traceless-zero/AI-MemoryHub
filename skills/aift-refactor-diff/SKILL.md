---
name: aift-refactor-diff
description: FunctionFlow 合同反转 · 收敛 diff 生成。当用户丢来 functionflow/v1 格式的 JSON（画布导出物）并要求据此修改真实代码/生成改动时使用。核心合同：画布 = 目标数据流声明（to-be），intent 字段 = 注脚；任务不是执行文字指令，而是生成让真实代码收敛到画布样子的最小 diff。触发词：functionflow、FL.json、收敛 diff、照图改码、数据流图改代码、as-is to-be、按方案改沙箱。
---

# FunctionFlow 合同反转 · 收敛 diff 生成

## 合同（已敲定，不要重新解释）
- 用户给的 JSON（`schema: functionflow/v1`）是**目标数据流声明（to-be）**，不是现状描述。
- `nodes[].data`（function / file / line / endLine / signature / comment）是函数块的定位与意图信息；`edges` 是数据流（from 的输出 → to 的入参，`label` = 下游参数名）。
- `intent` 字段是注脚，说明这张图表达的流程，不承担逐字指令。
- 节点/边可能带 `changed: true`（相对上次基线被用户改过）；没有此字段属正常，忽略即可。
- 图只表达数据流，不表达调用时序；DAG 拓扑序是唯一隐含顺序。
- 写入范围：方案获用户同意后，改动**只写 `ff_workspace/manifest.json` 映射的沙箱文件**（工作区由 `aift-sandbox-refactor` 管理）；原文件的写入属于其回归步骤，本 skill 严禁触碰原文件。无工作区（无 manifest）时保持旧行为：只输出 diff 不落盘。

## 执行流程
1. **解析图**：读 nodes/edges，按 `file` 分组得到涉及的文件清单，按拓扑理解数据流。
2. **扫描真实代码（as-is）**：读这些文件的真实内容，列出每个相关函数的实际签名、实现要点、**callers 清单**（谁调用了它）。JSON 里的 line/endLine 是导出时的行号，代码可能已漂移，一切以扫描到的真实代码为准。有 ff_workspace 工作区时，as-is 读 manifest 映射的**沙箱文件**（那是当前编辑态，首次等同原文件）；无工作区时读原文件。
3. **生成收敛 diff**，只允许三类操作：
   - 图中有、代码中无的连线 → **新增**（参数传递 / 调用）；
   - 代码中有、图中无的引用 → **移除或改道**；
   - 两边都有但形状不同 → **改造**签名 / 实现。
4. **多种收敛路径**：先列出候选方案与选择理由（简短），再给 diff，不静默选边。
5. **输出最小 diff**：只动必须动的行；保持既有代码风格；图中 signature 未变的函数**严禁改签名**。
6. **应用**：用户对方案点头后，把定稿改动**写入 manifest 映射的沙箱文件**（原文件不动——回归由 `aift-sandbox-refactor` 负责）；无工作区时仅输出 diff。

## 输出格式
1. ≤3 行的 as-is 摘要（当前实际怎么连的）。
2. diff（unified 格式或 before/after 代码块）。
3. 末尾附"新行号表"：每个被改函数的新 `function → line-endLine`，供用户回写 JSON 元数据。
4. 需要用户确认的开放点（如有），单独列出，不夹带在 diff 里。

## 红线
- 严禁超出图的范围自由发挥、顺手"优化"图外代码。
- 严禁给未验证的断言（引用代码时给出真实行号）。
- 严禁静默改签名：signature 冲突时停下来向用户确认。
- 严禁写原文件：落盘范围仅限 manifest 映射的沙箱路径；无工作区时只输出 diff 不落盘。
