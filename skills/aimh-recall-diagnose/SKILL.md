---
name: aimh-recall-diagnose
description: >
  召回失败三层诊断手册：该召回的内容没召回、明明存在却搜不到时，按
  「① FM 字段 → ② index.db → ③ 代码流程」从便宜到贵逐层定位，先查数据再怀疑代码。
  何时用（命中即加载）：召回失败、没搜到、为什么查不到、漏召回、检索不到、
  该命中没命中、regress 挂了找原因、诊断召回；铁律：先诊断后动手，改代码必须走沙箱。
---

# 召回失败诊断（骨架）

> **权威全文**：`memory/项目/AIMH-design-journal/工具与技能总览.md` §2.3（三层手册全文，含全部实测命令与真实案例）。
> **执行规则**：逐层召回（`mcp__aimh__memory_query_anchors`，`allow_abstain=true`）；**ABSTAIN → 停止并报告，勿即兴**；改代码必须走沙箱。

1. **第 0 步**：固定最小失败用例（查询原话 / 期望命中 / 实际返回）；查询走 AI 流 + scope 缩圈。召回键 `["召回失败诊断流程"]`
2. **第一层 FM 字段**：`scan_fm.py` + `lint_memory.py --all`——知识落盘了吗、四要素漏填=漏召回、about 泛化=挤出 top5（P08 红基线）。
3. **第二层 index.db**：`peek_index.py` + 锚点数比对——包不在索引=没 rebuild（最高频，即愈）；孤儿行=测试污染；rebuild 后仍不一致=引擎 bug 进第三层。
4. **第三层 代码流程**（先沙箱）：normalize_terms 切分 → waterfall_cut 裁切 → gate 饿死 → 拒答四闸 reason → 对照 regress 历史病（law_demo/coverage_gate/P08）。
5. **修复后必做**：改 FM→rebuild；改代码→14 项 regress 全绿 + 红基线原样；记 beat；全新失败模式回权威手册补一行。
