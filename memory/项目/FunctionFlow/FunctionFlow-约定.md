---
title: FunctionFlow 约定
summary: FunctionFlow 的死规矩。最重铁律：函数即黑盒（绝不展开内部控制流，图会爆炸）；边只表达数据流（绝不画调用边与执行顺序边——调用关系 AI 看 AST 即知，图上只留人的重排意图）；JSON 只存函数引用不存函数体（防副本与源码脱节）；端口弱类型任意连（类型检查交 AI）；忠实性边界一期不猜（as-is 与 to-be 之差即 diff 来源）。
tags: [ project, FunctionFlow, 铁律协作 ]
linked: [ 项目/FunctionFlow/FunctionFlow-需求清单.md, 项目/FunctionFlow/FunctionFlow-项目结构.md, 项目/FunctionFlow/FunctionFlow-架构.md ]
person: [{"用户": ["我", "用户本人"]}]
event_date: 2026-09-02
location: []
topic: [{"FunctionFlow": ["FF", "函数流图", "函数级可视化"]}, {"设计铁律": ["黑盒节点", "数据流边", "JSON引用"]}]
anchors:
  - Chapter: "图形设计铁律"
    about: "函数即黑盒：一个函数一个节点，内部 if/for/try 控制流绝不展开（展开会图爆炸，几百行函数变十几个节点）；边只表达数据流（A 的输出沿边流到 B 的输入），不画调用关系边（AI 看 AST 即知，画了冗余且与数据流拓扑相反造成交叉回环）、不画执行顺序边（拓扑序隐式表达）；端口弱类型：输入/输出口不标类型任意连，类型推断交 AI。"
    keywords: ["2026-09-02", "设计决策", "黑盒节点", "数据流边", "用户"]
  - Chapter: "JSON 忠实性铁律"
    about: "JSON 是图的序列化不涉及执行：只存节点/边/引用/批注四部分；只存函数引用（文件路径/函数名/行号）绝不存函数体副本——存了副本就会与源码脱节；schema=functionflow/v1，一份 JSON 两用途（导回还原图 / 交 AI 改源码）。"
    keywords: ["2026-09-02", "functionflow/v1", "JSON", "引用不存函数体", "用户"]
  - Chapter: "忠实性边界（一期不猜）"
    about: "提取器只抽调用图不做跨过程数据流分析，边不带参数级 label；import 但未调用的函数不产生边（import ≠ 数据流）；类构造（Order(...)）与异常构造不是函数节点；无编排代码时主链路不出边=as-is 现状，画布上人工补的数据流=to-be 意图，二者之差即 diff 来源——绝不静默脑补。"
    keywords: ["2026-09-02", "忠实性边界", "as-is", "to-be", "不猜"]
pkage_created: 2026-09-02
pkage_updated: 2026-09-02
---

# FunctionFlow 约定

## 铁律（不可违反）

- **函数即黑盒**：一个函数对应一个节点，节点上只展示函数名/签名/注释(docstring 合并)/文件位置行号，内部逻辑不展开——展开控制流会让图爆炸到无法阅读，细节交给源码承载。
- **边只表达数据流**：A 的输出值沿边流到 B 的输入。不画调用关系边、不画执行顺序边。调用关系是 AI 看 AST 就知道的冗余信息；三种语义（数据流/调用/顺序）混画必然大量交叉回环（数据流与调用拓扑经常相反）。
- **JSON 只存引用不存函数体**：函数体留在源文件里，JSON 存副本必与源码脱节。只存文件路径/函数名/行号。
- **端口弱类型任意连**：不标类型、不限连接，靠 AI 或运行时检查——最终消费者是 AI，前端不重复造类型推导。
- **忠实性边界一期不猜**：import ≠ 数据流；类构造/异常构造不是函数节点；无编排代码主链路不出边（as-is）。画布人工补的数据流 = to-be 意图，as-is 与 to-be 之差即 diff 来源。

## 协作约定

- 轻量定位：扫描函数、合并注释、可视化节点、导出 JSON——不做可视化编程语言（NoFlo 方向）、不做代码理解平台（CodeSee 方向）、不做可执行 workflow。
- 提取器双轨：ast 版零依赖兜底（纯 Python 源码场景），Tree-sitter 版做多语言（加语言 = `pip install tree-sitter-<lang>` + LANGUAGES 注册适配器，布局/导出逻辑复用）。
- 注释即节点说明：函数上方 comment 与 docstring 合并进节点，既给人看也喂 AI——这是与纯调用图工具的关键差异。
- ff_workspace 是默认的 JSON+代码副本工作与存储区：**每单业务一个目录（ff_workspace/<订单>/），目录内分 scripts/（代码副本）与 json/（该单全部 JSON）**；工作 JSON 用 ff_ws- 前缀；manifest.json 为原路径↔副本路径映射权威。项目根不设 json/ 与 src/（2026-09-03 用户手动定稿：曾试 run 同目录、平铺两案均废）。
