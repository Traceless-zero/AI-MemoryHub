---
title: FunctionFlow 需求清单
summary: FunctionFlow（函数级代码可视化与 AI 重构协作工具）的需求清单与 roadmap。已完成：双提取器（ast/Tree-sitter，产出逐条全等，含类方法限定名+嵌套def剔除+继承链双向解析）、免构建画布 canvas.html（vendor ReactFlow UMD，孤岛过滤+扇入预警实测通过）、--focus/--hops 子图、--strip-position AI 消费形态、AI 改码闭环验证（新增编排函数粒度，图上画的=源码里改的）。用户铁律：不要 node_modules（网盘目录保持轻）。进行中：按 focus 子图完成一次真实大规模审查。
tags: [ project, FunctionFlow, 需求待办 ]
linked: [ 项目/FunctionFlow/FunctionFlow-项目结构.md, 项目/FunctionFlow/FunctionFlow-约定.md, 项目/FunctionFlow/FunctionFlow-架构.md ]
person: [{"用户": ["我", "用户本人"]}]
event_date: 2026-09-02
location: []
topic: [{"FunctionFlow": ["FF", "函数流图", "函数级可视化"]}, {"代码审查": ["重构规划", "AI 改码"]}]
anchors:
  - Chapter: "画布路线变更（用户拍板）"
    about: "Next.js 脚手架路线被用户否决：node_modules 太重、网盘同步目录特意不要。改走免构建路线：vendor React/ReactDOM/ReactFlow UMD（306KB 静态文件）+ htm 免 JSX，canvas.html 单文件画布，浏览器直开，深交互（拖拽/连线/框选/小地图）全是开源库现成能力。src/*.tsx 降为参考实现。"
    keywords: ["2026-09-02", "免构建", "node_modules", "canvas.html", "用户"]
  - Chapter: "提取器修复（P0 完成）"
    about: "类方法误抽修复：类方法改限定名节点（Memory._conn），函数体内嵌套 def 按黑盒铁律剔除，self/cls/this 与显式类名前缀（EventPackage._parse_value）调用沿继承链解析（先向上查基类最近定义、落空再向下查子类实现——基类 self.X 运行时落子类，多态分发）。hma_core 实测：孤岛 23→9（余下全是构造器/@property/变量接收者等隐式调用，一期忠实不猜），重复名清零，ast 版与 ts 版节点集+边集逐条全等；orders 基线 8/4 保持。"
    keywords: ["2026-09-02", "类方法限定名", "嵌套def", "继承链解析", "用户"]
  - Chapter: "已完成里程碑"
    about: "v0.2：双提取器同产出（--focus/--hops/--dir/--strip-position）；canvas.html 免构建画布（orders 6/8 孤岛隐藏、hma_core 110/119+扇入30红色预警实测）；AI 改码闭环验证通过（orders 新增 process_order 编排函数串联五函数，to-be 图差集==AI 改码后源码再提取差集，intent 引号锚定名与实际出边吻合，既有函数/边零变化）。"
    keywords: ["2026-09-02", "v0.2", "闭环验证", "扇入预警", "用户"]
  - Chapter: "待办路线图"
    about: "P1：按 --focus 子图完成一次 hma_core 真实审查（分批路径见 daylog 2026-09-02 #13，修后图 119/195）；画布状态持久化往返一致性单测。P2：AI 消费形态进画布（复制 AI 形态按钮）；画布深链与提取产物工作流固化；多文件同名函数合并策略（现跨文件同名先到先得）。"
    keywords: ["2026-09-02", "分批审查", "持久化", "待办", "用户"]
pkage_created: 2026-09-02
pkage_updated: 2026-09-02
---

# FunctionFlow 需求清单

项目目标：把项目里的函数块提取成 ComfyUI 式可视化节点，人在画布上审查/重排函数间数据流，导出 functionflow/v1 JSON——一文件两用途：导回还原可视化图，或交给 AI 照图修改现有源码，形成「人定方向、AI 干活」的重构协作闭环。
定位：轻量小工具（扫描函数、合并注释、可视化节点、导出 JSON），不做重型平台、不做类型系统、不做可执行 workflow。
**工作约束（用户拍板）：不要 node_modules——画布走免构建 vendor 路线，项目目录保持轻。**

## 已完成

- [x] 【结构拍板·终版】ff_workspace 定为默认的 JSON+代码副本工作与存储区：**ff_workspace/<订单>/ 一单业务一个目录，目录内分 scripts/（代码副本）与 json/（该单 JSON）**；项目根 json/ 与 src/ 移除，样例与历史产物入 to_delete/。受影响面（canvas 深链/SKILL.md/README/manifest）同步回归 PASS。注：一天三案（run 同目录→平铺两目录→订单目录制），终版以用户手动布局为准；旧沙箱 process_order 改动经用户清理动作视为作废，orders 副本重置为干净原件（2026-09-03）

- [x] aift 双 skill 挂载 + 实战验证（2026-09-03）：orders 全流程跑通——建仓（manifest 3 条 draft）→ 映射（ff_ws-orders.json）→ to-be（ff_ws-orders-tobe.json，P1 后无 position 形态）→ refactor-diff 收敛 diff 写沙箱 → 结构验证 PASS（再提取差集==intent，9/9）→ 行为验证机制实证（PYTHONPATH 遮蔽 + namespace 回落）
- [x] 聚焦态导出报障销案：代码链完整（exportFlow 按 focusSet 过滤），用户所见为浏览器旧缓存；任务经用户撤销（2026-09-03）
- [x] 【skill 修复】aift-sandbox-refactor 行为验证配方 bug：原「PYTHONPATH=ff_workspace/sandbox 前缀跑入口」在从项目根跑时 sys.path[0]=''（CWD）抢先，遮蔽必失效；改为双路径 PYTHONPATH（沙箱;项目根）+ 中性 CWD 或 `python -P` 两种姿势，已回写项目源并同步挂载（2026-09-03）

- [x] Python ast 提取器 `extract_flow.py`：纯标准库零依赖，函数节点+调用边+拓扑分列布局（2026-09-02）
- [x] Tree-sitter 多语言提取器 `extract_flow_ts.py`：py/js/ts 适配器，与 ast 版**节点集+边集逐条全等**（2026-09-02）
- [x] 【P0】提取器噪声修复：类方法限定名（Memory._conn）、函数体内嵌套 def 剔除、self/cls/类名前缀调用沿继承链双向解析（向上基类/向下子类）；hma_core 孤岛 23→9、重复名清零、orders 基线 8/4 保持（2026-09-02）
- [x] 【P0·路线变更】画布：用户否决 node_modules，改免构建 `canvas.html`（vendor ReactFlow UMD 306KB + htm），浏览器直开，浏览器实测渲染/交互/深链通过（2026-09-02）
- [x] 【P1】画布过滤与预警：孤岛节点默认隐藏（开关可切）、扇入≥5 琥珀/≥10 红色映射尺寸与颜色（hma_core `Memory._conn` 扇入 30 红色高危实测）（2026-09-02）
- [x] 【P1】`--focus <函数> --hops <N> --dir down|up|both` 子图提取：query_anchors 一跳 14 节点回可读规模；_conn 上游两跳 51 节点影响面；歧义名报错列候选（2026-09-02）
- [x] 【P2】`--strip-position` AI 消费形态（画布坐标置 null）+ AI 改码闭环验证：orders 新增 `process_order` 编排函数串联既有五函数，机器 diff 证明 to-be 图差集 == after 源码再提取差集，intent 引号锚定与实际出边吻合（2026-09-02）
- [x] 【P2·单 JSON 拍板】AI 形态不另存文件：position 对 AI 是惰性数据（读图忽略即可），一份 to-be JSON 两用途（铁律口径）；剥离 position 降级为省 token 可选步骤（提取器 --strip-position / 画布「复制 AI 形态」按钮）（2026-09-03）
- [x] 【画布功能补齐】「＋ 节点」新增 to-be 节点、双击节点改批注（comment）、双击边改标签（label）、「复制 AI 形态」按钮、隐藏 ReactFlow attribution 徽章（MIT 本地工具，proOptions）（2026-09-03）
- [x] functionflow/v1 JSON 导出、8+ 份真实产出、demo.html 静态样张（2026-09-02）
- [x] demo 实测结论：纯语言描述重排意图歧义到不可用，图文混合（图锚定指代 + intent 语言承载变更动词）为正解（2026-09-02）

## 进行中

- [ ] hma_core 真实审查：用 `--focus` 子图按分批路径（daylog 2026-09-02 #13）跑一轮真实审查，修后全图 119 节点/195 边

## 未完成

- [ ] 【P2】画布状态持久化：刷新丢失画布改动，候选方案 localStorage 草稿自动保存 + 导入导出往返一致性单测
- [ ] 【P3】画布撤销/重做；大图节点搜索定位
- [ ] 【P3】跨文件同名函数合并策略（现先到先得）；跨文件继承解析（现同文件为限）
