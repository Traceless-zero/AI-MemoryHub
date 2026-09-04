---
title: AI-FunctionTopo 开发日志：图层系统与坐标收拢（2026-09-03 下半场）
summary: AI-FunctionTopo（原 FunctionFlow）画布 2026-09-03 下半场大版本开发日志：重置画布演进为多图层系统（左侧 PS 式抽屉、双击重命名/清空/重置/各图层独立视口）+ 右键节点菜单；P1/P2/P3 全部关闭——坐标收拢渲染侧（JSON 不再携带 position，重排深度改调用图最长路径松弛）、language 回导修复、导出去噪；正式命名 AI-FunctionTopo（AI-TopoCode/AITC 清障否决）；双 skill 体系（aift-sandbox-refactor 沙箱工作流 + aift-refactor-diff 应用职权）挂载收口。
tags: [ FunctionFlow, AI-FunctionTopo, 开发日志, 图层系统 ]
linked: [ 项目/FunctionFlow/FunctionFlow-架构.md, 项目/FunctionFlow/FunctionFlow-JSON合同钉死.md, 项目/FunctionFlow/FunctionFlow-需求清单.md ]
person: [{"用户": ["我", "用户本人"]}]
event_date: 2026-09-03
location: []
topic: [{"FunctionFlow": ["FF", "函数流图", "函数级可视化", "AI-FunctionTopo"]}, {"系统架构": ["图层系统", "坐标收拢", "最长路径松弛", "遮蔽运行"]}]
anchors:
  - Chapter: "图层系统与右键菜单"
    about: "重置画布演进成多图层系统：拖入 JSON=新图层（顶部标签条被用户否决→左侧 PS 式抽屉面板），图层双击重命名、✕ 关闭、各图层独立记忆视口（rfInstance get/setViewport 随槽存取）；右键节点菜单（删除/复制/修改信息，复制后只选中新节点）；清空画布=清当前图层停在空画布，重置图层=还原导入时初始 JSON（槽位存 origin）。抽屉伸缩不带视图框的 bug 用 300ms rAF 逐帧跟随 updateMiniFrame 修复。"
    keywords: ["2026-09-03", "canvas.html", "图层抽屉", "ff_workspace", "用户"]
  - Chapter: "坐标收拢渲染侧（P1/P3 关闭）"
    about: "用户洞察：坐标的生产者只有提取器（最长路径机械推导）与渲染侧（重排+拖拽），AI 从不产坐标，且导入即重排覆盖——JSON 里的坐标纯冗余。落地：fromReactFlow 不再输出 position（单档导出即 AI 档，省约 18%）；relayoutNodes(nds, es) 深度来源改为调用图最长路径松弛（与提取器同款算法），层内排序按 data.line；无坐标 JSON 回导正常分层（P3 塌层消失）。验证：坐标无关性（全零坐标输入输出一致）+ 边单调性（orders 8/8；aimh 190/195，5 条违反全是递归环边）+ 119 节点 3ms。"
    keywords: ["2026-09-03", "fromReactFlow", "坐标收拢", "最长路径松弛", "DeepSeek"]
  - Chapter: "导出去噪与 language 回导修复（P2 关闭）"
    about: "导出剔除 generatedAt/type/占位零值（AI 零信号噪音）；language 字段（python/ts）全链路打通：导入保存 → 标签快照随槽走 → 导出带回，抽出真实 fromReactFlow 跑函数级断言 3/3 PASS。"
    keywords: ["2026-09-03", "fromReactFlow", "导出去噪", "language", "用户"]
  - Chapter: "双 skill 体系与挂载收口"
    about: "aift-sandbox-refactor（新建）：ff_workspace 工作区五步闭环（建仓→映射→改动循环→验证→回归），无 backup 层（改错重新复制原文件即重置），验证用遮蔽运行（PYTHONPATH=ff_workspace/sandbox 前缀，改过的模块命中沙箱副本）不需要放回原位；aift-refactor-diff（修订）：获得应用职权——用户同意方案后写 manifest 映射的沙箱文件，原文件严禁触碰。旧挂载 functionflow-refactor-diff 移入 to_delete，两个 aift skill 装入 WorkBuddy 挂载目录（MOUNT_SYNC_PASS，新会话生效）。"
    keywords: ["2026-09-03", "ff_workspace", "遮蔽运行", "PYTHONPATH", "用户"]
  - Chapter: "命名定稿 AI-FunctionTopo"
    about: "AI-TopoCode(AITC) 因 topocode.cn 同赛道竞品全名撞车 + AITC 被電通総研 AI 部门占用被标准④清障否决；用户换尾缀 AI-FunctionTopo 清障通过（无同名产品，7 个 TLD 域名未解析，最近邻 Julia 库 FuncTopo 类型名弱冲突）。品牌落 README 与画布 UI（title/工具栏/空态/帮助）；技术标识符（schema functionflow/v1、skill 名、文件名）冻结待统一迁移。"
    keywords: ["2026-09-03", "AI-FunctionTopo", "topocode.cn", "README", "用户"]
pkage_created: 2026-09-03
pkage_updated: 2026-09-03
---

# AI-FunctionTopo 开发日志：图层系统与坐标收拢（2026-09-03 下半场）

记录 AI-FunctionTopo（原 FunctionFlow，正式命名见下）画布 2026-09-03 下午至晚间的大版本演进。上午的抽屉 bug 修复（scrollIntoView 根因 + Kimi K3 交接）见 daylog 2026-09-03 beat 14/15；本篇从下午的右键菜单需求起，到晚间双 skill 挂载收口止。

## 图层系统与右键菜单

- **右键节点菜单**：删除节点（连带边 + 清源码/聚焦残态）、复制节点（新 id 偏移 + 边复制 + 只选中新节点）、修改节点信息（预填面板；文件与行号是源码派生值不开放编辑）。
- **重置画布 → 多图层**：用户最初要多图层（PS 式），中间经历「顶部标签条」（被否，视觉不好）→ 最终形态：**左侧 PS 图层面板抽屉**（190px，可收拉，把手镜像右抽屉）。一个载入文件 = 一个图层，拖 JSON 追加不覆盖；图层双击重命名（内联 input，Enter/失焦保存 Esc 取消）、✕ 单独关闭、点击切换。
- **图层操作三件套**：清空画布（清当前图层内容停在空画布，不退遮罩）、重置图层（还原导入时初始 JSON，槽位存 origin）、新建画布（开空白图层）。
- **各图层独立视口**：rfInstance get/setViewport 随槽位存取（用户报告共享视口后修正为浏览器标签语义）。
- **bug：抽屉伸缩不带视图框**——视图框由 updateMiniFrame 按 getScreenCTM 实测定位置，触发器只有 onMove/节点变化/resize，CSS transition 滑动无触发器。修法：把手 onClick 里开 300ms rAF 逐帧跟随。

## 坐标收拢渲染侧（P1/P3 关闭）

- **用户洞察**：坐标的生产者只有提取器（最长路径机械推导，x=40+lv*360）与渲染侧（重排+拖拽），AI 从不产坐标；且导入即自动重排覆盖——JSON 里的坐标除了给旧重排的「x 聚簇」当深度输入外纯冗余。
- **落地**：`fromReactFlow` 节点不再输出 position（单档导出即 AI 档，每节点省 4 行约 18%）；`relayoutNodes(nds, es)` 签名加边参数，深度来源改为**调用图最长路径松弛**（level[to]=max(level[to],level[from]+1) 迭代至不动点，与 extract_flow.py 同款算法），层内排序按 data.line 回退 id。
- **验证**（真实函数抽出跑 node 断言）：坐标无关性——全零坐标输入 vs 原坐标输入输出逐节点一致（orders + aimh 2/2 PASS）；边单调性——orders 8/8、aimh 190/195（5 条违反全在递归环 SCC 上，分层布局对环必然违反，且旧 JSON 反推的提取器布局自身违反 26 处）；119 节点 3ms。
- 期间评估过 DeepSeek 的 graph/canvas 拆分方案：分离思想与拓扑兜底采纳，v2 全量改名不采纳（打断提取器/skill/样例，示例丢 function/line/comment/label/intent 产品必需字段；「prompt 嘱咐 AI 别读」不省 token）。

## 导出去噪与 language 回导修复（P2 关闭）

- 导出剔除 generatedAt（diff 噪音）、type:"function"（每节点重复常量）、line/endLine 占位零值、fanIn（画布派生）。
- language（python/ts）全链路：导入保存 → 标签快照随槽走 → 导出带回（fromReactFlow 第 5 参，未设置时 JSON.stringify 自动剔键）；清空画布置空、重置图层从 origin 还原。函数级断言 3/3 PASS。

## 双 skill 体系与挂载收口

- **aift-sandbox-refactor**（新建）：ff_workspace 工作区五步闭环——建仓（复述清单等确认）→ 映射（提取器跑沙箱文件）→ 改动循环（to-be JSON → refactor-diff 出方案 → 写沙箱）→ 验证 → 回归。无 backup 层（原文件回归前就是干净参照物，改错重新复制覆盖即重置）。
- **验证不需要放回原位**：结构验证（沙箱重提取 → 与 to-be JSON 差集对照）；行为验证（遮蔽运行：PYTHONPATH=ff_workspace/sandbox 前缀，改过的模块命中沙箱副本、未复制模块回落原路径）。注意 __init__.py 常规包整包遮蔽的坑。
- **aift-refactor-diff**（修订）：获得应用职权——用户同意方案后把改动写入 manifest 映射的沙箱文件；原文件写入属 sandbox-refactor 回归步骤，严禁触碰；无工作区保持旧行为只输出 diff。
- **挂载收口**：旧挂载 functionflow-refactor-diff 移入 to_delete/mounted-functionflow-refactor-diff；两个 aift skill 装入 C:\Users\HP\.workbuddy\skills\（diff -r 与项目源一致）。项目内 skills/ 为权威源。新 skill 名新会话生效。

## 命名定稿 AI-FunctionTopo

- 第一版 AI-TopoCode (AITC) 被标准④清障否决：TopoCode（topocode.cn + GitHub，Tree-sitter/调用图/AI 分析，同赛道竞品）全名撞车；AITC 被電通総研 AI Transformation Center 占用。
- 换尾缀 **AI-FunctionTopo** 清障通过：无同名产品/仓库；7 个 TLD 域名未解析；最近邻 Julia 库 TopoChains.jl 的 FuncTopo 类型名（弱冲突，词源相同印证语义自然）。
- 品牌落 README（标题 + 正文 2 处）与画布 UI（浏览器 title、工具栏品牌、空态标题、帮助标题）。
- 技术标识符冻结待统一迁移：schema functionflow/v1、skill 名 functionflow-*（已改 aift-*）、文件名 canvas.html / extract_flow*.py / json/functionflow-*.json、代码标识符 FunctionFlowEdge / FunctionFlowFile。
