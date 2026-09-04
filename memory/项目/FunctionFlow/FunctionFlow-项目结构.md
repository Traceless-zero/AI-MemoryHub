---
title: FunctionFlow 项目结构
summary: FunctionFlow（正式名 AI-FunctionTopo，技术标识符暂仍 functionflow 系）的目录与文件布局。根目录 6 项：双提取器（extract_flow.py ast / extract_flow_ts.py Tree-sitter，产出全等）、免构建画布 canvas.html + vendor/ 静态库（无 node_modules）、ff_workspace/（默认的 JSON+代码副本工作与存储区：每单业务一子目录，代码副本与该业务全部 JSON 同目录；manifest.json 映射权威；samples/ 收只读样例与素材）、skills/（aift 双 skill 权威源）、to_delete/（清理暂存待删）。原项目根 json/ 与 src/ 已按用户指令移除，内容迁入 ff_workspace/samples/。
tags: [ project, FunctionFlow, 目录布局 ]
linked: [ 项目/FunctionFlow/FunctionFlow-需求清单.md, 项目/FunctionFlow/FunctionFlow-约定.md, 项目/FunctionFlow/FunctionFlow-架构.md ]
person: [{"用户": ["我", "用户本人"]}]
event_date: 2026-09-03
location: []
topic: [{"FunctionFlow": ["FF", "函数流图", "函数级可视化"]}, {"项目结构": ["目录布局"]}]
anchors:
  - Chapter: "根目录布局（2026-09-03 精简后）"
    about: "根目录 6 项：README.md（唯一正式 README）、canvas.html（免构建画布：多图层/聚焦/流入预警/源码审查/抽屉侧栏/空态遮罩，品牌已落 AI-FunctionTopo）、extract_flow.py 与 extract_flow_ts.py（双提取器，--focus/--hops/--dir/--strip-position）、ff_workspace/（工作与存储区）、skills/（aift-refactor-diff + aift-sandbox-refactor 权威源，挂载 ~/.zcode/skills）、to_delete/（清理暂存：demo.html/docx/Next.js tsx/demo 系 JSON/src/README.md 等 14+ 项，待用户整体删除）、vendor/（react 18.3.1 / reactflow 11.11.4 UMD / htm，共 ~306KB）。"
    keywords: ["2026-09-03", "根目录", "ff_workspace", "精简", "用户"]
  - Chapter: "ff_workspace 工作区合同"
    about: "ff_workspace/ 是默认的 JSON+代码副本工作与存储区，结构=ff_workspace/<run>/（一单业务一目录：代码副本保持原相对路径 + 该业务全部 JSON 同目录共存）+ manifest.json（原路径↔工作区路径↔状态 draft/merged 映射权威）+ samples/（只读样例与素材：orders、orders_after、aimh 源码 + functionflow 系全部样例 JSON）。orders-run/ 是首个实战 run（service.py 副本含 process_order 改动，回归待用户拍板）。新 JSON 一律落所在 <run>/，项目根不再设 json/ 与 src/。"
    keywords: ["2026-09-03", "工作区", "manifest", "samples", "同目录"]
pkage_created: 2026-09-02
pkage_updated: 2026-09-03
---

# FunctionFlow 项目结构

## 目录布局（2026-09-03 精简后）

```
functionflow/                     # 正式名 AI-FunctionTopo（技术标识符 functionflow 系待迁移）
├── README.md                     # 唯一正式 README
├── canvas.html                   # 主画布（免构建 vendor ReactFlow UMD；多图层/聚焦/流入预警/
│                                 #   源码审查/意图框/抽屉侧栏/金字塔→方块/空态遮罩/右键菜单）
├── extract_flow.py               # Python ast 提取器（零依赖；--focus/--hops/--dir/--strip-position）
├── extract_flow_ts.py            # Tree-sitter 多语言提取器（py/js/ts；产出与 ast 版逐条全等）
├── vendor/                       # canvas 本地依赖（react 18.3.1 / react-dom / reactflow 11.11.4 UMD /
│                                 #   htm / reactflow.css，~306KB，无 node_modules）
├── ff_workspace/                 # 【默认的 JSON+代码副本工作与存储区：每单业务一个目录】
│   ├── manifest.json             # 映射权威：original ↔ sandbox(副本路径) ↔ status
│   └── orders/                   # 实战订单（scripts/ 三件为干净原件；旧沙箱 process_order 改动已作废）
│       ├── scripts/              # 代码副本（唯一可编辑区）
│       └── json/                 # 该单全部 JSON（orders 示例图、ff_ws-orders 再提取）
│   （旧 orders-run 副本、ff_ws tobe/after、orders_after、aimh、functionflow-* 样例等已入 to_delete/）
├── skills/                       # aift-refactor-diff + aift-sandbox-refactor 的权威源（挂载 ~/.zcode/skills）
└── to_delete/                    # 清理暂存（demo.html、docx、Next.js tsx、demo 系 JSON、src/README.md、
                                  #   types.ts 等，待用户整体删除）
```

> 项目根不再有 json/ 与 src/（2026-09-03 用户指令移除）；样例与历史产物大入 to_delete/。
> 副本内 import 的 src.common 等模块是 fixture 性质引用，实际不存在、从不执行。
> 本文件只装结构。铁律/约定/架构决策进 约定.md / 架构.md。
