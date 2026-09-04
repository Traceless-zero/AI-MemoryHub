---
title: AI-FunctionTopo（原 FunctionFlow）架构
summary: AI-FunctionTopo（原 FunctionFlow）的系统设计：三层架构（Tree-sitter/ast 函数提取层 → 免构建 React Flow UMD 画布层 → functionflow/v1 JSON 导出层），把 AI 长代码的审查认知负担转化为画布上的结构化重排意图。用户铁律不要 node_modules，画布走 vendor UMD 免构建路线。核心创新是市场空缺的第三步——提取-可视化-重排-导出 JSON 给 AI，闭环已经机器验证。2026-09-03 起：JSON 不再携带 position（坐标收拢渲染侧，布局=调用图最长路径松弛+真实高度派生）、多图层系统（一文件一图层，左抽屉）、双 skill 工作流（aift-sandbox-refactor + aift-refactor-diff）、正式命名 AI-FunctionTopo。
tags: [ project, FunctionFlow, AI-FunctionTopo, 系统设计 ]
linked: [ 项目/FunctionFlow/FunctionFlow-需求清单.md, 项目/FunctionFlow/FunctionFlow-项目结构.md, 项目/FunctionFlow/FunctionFlow-约定.md ]
person: [{"用户": ["我", "用户本人"]}]
event_date: 2026-09-02
location: []
topic: [{"FunctionFlow": ["FF", "函数流图", "函数级可视化"]}, {"系统架构": ["三层架构", "Tree-sitter", "React Flow", "坐标收拢", "图层系统"]}]
anchors:
  - Chapter: "系统是什么"
    about: "把项目函数块提取成 ComfyUI 式可视化节点画布：人审查函数组织方式、拖拽重排数据流、导出 functionflow/v1 JSON；一份 JSON 既导回还原可视化图，也交给 AI 照图修改源码——起点是真实项目代码而非空白画布，痛点是 AI 生成代码越长人审查的认知负担越重。"
    keywords: ["2026-09-02", "系统设计", "ComfyUI", "可视化画布", "用户"]
  - Chapter: "三层架构"
    about: "提取层：Python ast 零依赖版与 Tree-sitter 版双轨，产出节点集+边集逐条全等；类方法限定名节点（Memory._conn），嵌套 def 按黑盒剔除，self/cls/this 与显式类名前缀调用沿继承链解析（先向上基类最近定义、落空向下子类实现=多态分发），同文件为限。可视化层：canvas.html 免构建画布（vendor ReactFlow 11 UMD + htm 免 JSX），孤岛过滤默认开、扇入≥5琥珀/≥10红映射尺寸颜色、?src= 深链直载提取产物。导出层：functionflow/v1 JSON（nodes 含 position/edges/intent 人工意图层）。"
    keywords: ["2026-09-02", "三层架构", "免构建", "UMD", "继承链解析"]
  - Chapter: "画布路线决策（用户拍板）"
    about: "Next.js 脚手架路线被用户否决（node_modules 太重，网盘同步目录特意保持轻）。替代：reactflow@11 官方 UMD 构建（dist/umd/index.js 155KB）+ React/ReactDOM UMD + htm，vendor/ 静态文件浏览器直开，深交互全是开源库现成能力；src/*.tsx 降为参考实现。踩坑：const {ReactFlow} = ReactFlow 解构命中同名 const 的 TDZ，必须先取命名空间 RF 再解构改名 Flow。"
    keywords: ["2026-09-02", "免构建", "UMD", "TDZ踩坑", "用户"]
  - Chapter: "市场空隙与核心创新"
    about: "CodeSee（重合度最高的产品）2024 年被 GitKraken 收购后停摆，且无地图导出 JSON、不改源码、AI 只做摘要；调用图可视化工具（go-callvis/pycallgraph 等）单向只读；节点式编程（Nodes.io/NoFlo）从空白画布搭；竞品 Cursor/Claude Code 对话式表达多函数重排意图低效——「提取函数-可视化-重排-导出 JSON 给 AI」的完整闭环是赛道空缺，即本项目核心创新。闭环已机器验证：orders 新增 process_order 编排函数，to-be 图差集 == AI 改码后源码再提取差集。"
    keywords: ["2026-09-02", "市场空隙", "CodeSee", "核心创新", "闭环验证"]
  - Chapter: "2026-09-03 增补：坐标收拢渲染侧、图层系统与命名"
    about: "坐标不进 JSON：坐标的生产者只有提取器（最长路径机械推导）与渲染侧（重排+拖拽），AI 从不产坐标且导入即重排覆盖，交换格式里纯冗余。布局改渲染侧派生：relayoutNodes 深度=调用图最长路径松弛（提取器同款算法），层内排序按 data.line，导出省约 18%，无坐标 JSON 回导正常分层。多图层系统：一文件一图层（左抽屉），重命名/清空/重置/独立视口。双 skill：aift-sandbox-refactor 管工作区生命周期（验证用 PYTHONPATH 遮蔽运行），aift-refactor-diff 管方案并写沙箱文件。正式命名 AI-FunctionTopo（AI-TopoCode/AITC 被 topocode.cn 竞品与電通総研清障否决）。"
    keywords: ["2026-09-03", "AI-FunctionTopo", "坐标收拢", "图层系统", "用户"]
pkage_created: 2026-09-02
pkage_updated: 2026-09-03
---

# AI-FunctionTopo（原 FunctionFlow）架构

## 系统是什么

把项目里的函数块提取出来，变成像 ComfyUI 那样的可视化节点：人在画布上拖拽、连线、重新组织函数之间的数据流，导出一个 functionflow/v1 JSON。这个 JSON 有两种用途——导入回工具还原可视化图，或交给 AI 照着图修改现有源码。

起点是一个朴素痛点：AI 生成的代码越来越长，逐行阅读几百行脚本很难快速建立整体结构认知；把函数块抽出来像看流程图一样看组织方式，审查效率大幅提升。更进一步，人在画布上重排函数调用流程再让 AI 执行重构意图，形成「人定方向、AI 干活」的协作闭环。

## 三层架构

```
函数提取层（Tree-sitter / ast，产出全等）
  → extract_flow.py（Python ast，零依赖标准库）
  → extract_flow_ts.py（Tree-sitter：LANGUAGES 注册表按扩展名选 grammar，
     内置 python/javascript/typescript；加语言 = 装 grammar 包 + 注册适配器）
  → 解析函数定义 + docstring，类方法限定名（Memory._conn），
     嵌套 def 剔除（黑盒不展开），self/cls/类名前缀调用沿继承链解析（向上基类/向下子类），
     调用图拓扑深度分列布局
可视化交互层（canvas.html，免构建 vendor UMD）
  → vendor/：react 18.3.1 UMD + react-dom UMD + reactflow 11.11.4 UMD + htm（共 ~306KB）
  → 拖拽/缩放/框选/连线/小地图（ReactFlow 现成能力）；业务逻辑移植自 src/flow-canvas.tsx
  → 孤岛节点默认隐藏（开关可切）；扇入 ≥5 琥珀 / ≥10 红，映射边框颜色与节点尺寸，随人工补边实时重算
  → ?src=json/xxx.json 深链直载提取产物（http 服务下）；拖 JSON 文件进窗口 = 导入
导出层（functionflow/v1 JSON）
  → schema/projectRoot/language + nodes(不含 position) + edges + intent(人工意图层)
  → 坐标不进 JSON（2026-09-03 起）：布局由渲染侧计算（见「2026-09-03 增补」节）；提取器 --strip-position 兼容保留
  → 一份 JSON 两用途：导回还原图 / 交 AI 照图改源码
```

关键决策（为什么这样）：节点黑盒保图的简洁性；边只留数据流让人意图干净；端口弱类型砍掉类型推导复杂度；JSON 只存引用保证与源码不脱节；画布免构建 vendor 路线尊重「不要 node_modules」的目录轻量约束。

## 市场空隙与核心创新

调研结论：现有方案只覆盖了部分环节。CodeSee 的 Function Maps 最接近但已于 2024 年被 GitKraken 收购后停摆（无导出 JSON、Edit Map 不改源码、AI 只做摘要）；调用图可视化（go-callvis、pycallgraph 等）单向只读不能拖拽重排；节点式可视化编程（Nodes.io、NoFlo）从空白画布起步而非已有代码；代码转流程图只能看不能编辑回写。

**「提取函数 → 可视化 → 重排 → 导出 JSON 给 AI」的完整闭环目前市面上没有产品实现，即本项目核心创新。** 竞品定位是对话式重构工具（Cursor、Claude Code），但对话表达复杂的多函数重排意图非常低效——可视化节点图天然适合表达这种结构化意图，本项目是「AI 辅助重构的可视化交互层」。闭环已机器验证（2026-09-02）：orders 画布补 `process_order` 编排节点 + intent，AI 照图只新增编排函数串联既有五函数，再提取差集与图上意图完全一致。

## 模块间关系

- 提取器（extract_flow*.py）只产 JSON，不知道前端存在；canvas.html 只消费 JSON 渲染画布。
- `src/orders/`、`src/orders_after/`、`src/aimh/hma_core.py`、`src/demo/` 是审查素材源码（提取器的输入），不是画布依赖。
- 闭环路线：源码 → 提取 origin JSON → 画布导入渲染 → 人工重排/补数据流边 → 导出 to-be JSON（+intent，无坐标）→ AI 照图改源码（一期只限新增编排函数）→ 再提取 after JSON → 机器 diff 验证差集 == 画布意图。

## 2026-09-03 增补：坐标收拢渲染侧、图层系统与命名

- **坐标收拢渲染侧（P1/P3 关闭）**：JSON 不再携带 position——坐标的生产者只有提取器（最长路径机械推导）与渲染侧（重排+拖拽），AI 从不产坐标，且导入即自动重排覆盖，交换格式里纯冗余。布局改渲染侧派生：relayoutNodes 深度来源 = 调用图最长路径松弛（与提取器同款算法），层内排序按 data.line；导出体积省约 18%。无坐标 JSON / AI 改图新增节点回导正常分层（塌层问题消失），旧版带坐标文件兼容导入。
- **多图层系统**：一个载入文件 = 一个图层（左侧 PS 图层面板抽屉，可收拉），拖 JSON 追加不覆盖；图层双击重命名 / ✕ 关闭 / 清空（清当前图层停在空画布）/ 重置（还原导入初始 JSON，槽位存 origin）/ 各图层独立记忆视口（get/setViewport 随槽存取）。右键节点菜单：删除 / 复制 / 修改信息。
- **双 skill 工作流**：aift-sandbox-refactor 管 ff_workspace 工作区生命周期（建仓→映射→改动循环→验证→回归；验证 = 结构重提取对照 + 遮蔽运行 PYTHONPATH=ff_workspace/sandbox，原文件零接触，无需放回原位）；aift-refactor-diff 管理解 JSON → 给方案 → 用户同意后写沙箱文件（原文件严禁触碰）。项目内 skills/ 为权威源，挂载目录为副本。
- **命名定稿 AI-FunctionTopo**：AI-TopoCode(AITC) 被 topocode.cn 同赛道竞品全名撞车 + 電通総研 AITC 占用，标准④清障否决；AI-FunctionTopo 清障通过（无同名产品、7 TLD 域名未解析、最近邻 Julia 库 FuncTopo 类型名弱冲突）。品牌已落 README 与画布 UI；schema functionflow/v1 与文件名冻结待统一迁移。
