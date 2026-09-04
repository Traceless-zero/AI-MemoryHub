---
title: 碧蓝航线本地Wiki 架构
summary: blhx-wiki 的系统设计与数据流。管线：BWIKI api.php wikitext → 深度感知模板解析 → 规范化 JSON（ships/equipment）→ demo 数据生成（含弹种×装甲威胁矩阵）→ 零依赖静态前端。前端为纯 HTML/CSS/JS 无框架无构建，渐进增强（html.js 门控）。
tags: ["project", "碧蓝航线本地Wiki", "系统设计"]
linked: ["项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-需求清单.md", "项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-项目结构.md", "项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-约定.md"]
person: [{"用户": ["我", "用户本人"]}]
event_date: "—"
location: []
topic: [{"碧蓝航线本地Wiki": ["blhx-wiki", "系统设计", "数据管线"]}, {"威胁矩阵": ["对甲比例", "弹种"]}]
anchors:
  - Chapter: "数据管线"
    about: "api.php action=parse 取 wikitext → parse_template_params 做 {{}}/[[]] 深度感知的顶层 |key=value 解析 → 无损保留全部模板参数并提取 core 常用字段、对甲比例 '140-110-90' 归一化为 {轻,中,重} 小数 → ships.json/equipment.json；make_demo.py 另从装备缓存按弹药分组统计均值生成威胁矩阵。"
    keywords: ["2026-09-01", "crawler目录", "wikitext解析", "parse_template_params", "用户"]
  - Chapter: "前端动效架构"
    about: "零依赖动效引擎 ship.js：hero 揭幕多路径兜底、IntersectionObserver 滚动浮现与计数动画（ease 指数缓动）、hero 鼠标+滚动视差（rAF 循环）、scrollspy；CSS 侧 .reveal 基元 + html.js 门控渐进增强，reduced-motion 专用分支。"
    keywords: ["2026-09-01", "app前端", "渐进增强", "ship.js", "用户"]
  - Chapter: "配装数据链"
    about: "BWIKI 舰娘页 wikitext 模板参数里 pve配装推荐1 为空，真正的配装推荐只在渲染页 HTML 的表格模块里（攻略组认证、按优先级行排列）；解析 data/raw/企业.html 的 <tr>/<td> 提取装备名+评语，图标 URL 由 thumb 路径去 /thumb/ 与尺寸后缀还原为原图，21 条结构化落 enterprise_gear.json。"
    keywords: ["2026-09-01", "data目录", "配装推荐", "enterprise_gear.json", "用户"]
pkage_created: 2026-09-02
pkage_updated: 2026-09-02
---

# 碧蓝航线本地Wiki 架构

## 系统是什么

把 BWIKI 的 MediaWiki 结构化数据镜像成本地纯静态 wiki：**离线可查、无广告、可自定义展示**。
设计原理：爬取层与展示层完全解耦——wikitext 原文缓存是权威源，JSON 是规范化视图，静态页只是其中一种渲染产物（未来可换/可批量）。

## 数据管线

```
BWIKI api.php (action=parse, prop=wikitext)
  → crawl_blhx.py: enumerate_category 全量枚举 + 磁盘缓存断点续爬
  → parse_template_params: {{ }} / [[ ]] 深度感知，只拆顶层 |key=value
  → data/ships.json / equipment.json   （无损 params 全保留 + core 常用字段提取；
                                          对甲比例 "140-110-90" → {轻:1.4, 中:1.1, 重:0.9}）
  → make_demo.py → app/data/enterprise.json
      威胁矩阵 = 装备缓存按"弹药"分组、对比例逐维取均值（样本数随行记录）
  → app/index.html（现阶段手写静态样品；下一步数据驱动渲染）
```

关键点：模板参数解析必须做**嵌套深度感知**（舰娘图鉴模板里有大量嵌套模板与链接，朴素 split 会切错）；规范化 JSON 无损保留全部 params，core 只是把常用字段提升出来，回滚/重解析零成本。

## 前端动效架构

零依赖（无框架、无构建、无 CDN）：`base.css` 设计令牌（金 #d8bd8a 单一彩色锚点、hairline 分隔、SF Pro 字体栈）+ `ship.css` 区块组件 + `ship.js` 动效引擎。

- **揭幕（.loaded）**：多路径兜底——img.complete 快路径 / decode() / load+error 事件 / 900ms 硬超时，once-guard 防重入；CSS 初始隐藏态全部挂 `html.js` 门控（ship.js 首行 `documentElement.classList.add("js")`），JS 缺席 = 静态可见页面（渐进增强）。
- **滚动浮现（.reveal）**：IntersectionObserver threshold 0.18，进入视口加 .in 并触发子元素 data-count 计数动画（指数缓动 1100ms）、矩阵条形 --w、效率 gauge。
- **视差**：rAF 循环读 scrollY + 鼠标位置，hero-art/hero-copy 分层位移与淡出；reduced-motion 全分支停用。
- **scrollspy**：锚点导航高亮当前区块（rootMargin -38%/-52% 带状触发），滚回 hero 清空高亮。
- **背景氛围层**：官方立绘/誓约/换装图 blur(58-70px)+压暗+mask 渐隐，替代纯黑底；官方立绘自带的金色天光底用 radial mask 融进暗色页面。

## 配装数据链

配装推荐在 wikitext 模板参数里为空（`pve配装推荐1=`），**只在渲染页 HTML 的表格里**。数据链：渲染页快照 `data/raw/企业.html` → 按 `<tr>/<td>` 解析出「槽位 → 装备名+T级+评语（按优先级行序）」→ 图标 URL 从 thumb 路径去掉 `/thumb/` 与尺寸后缀还原原图 → `app/data/enterprise_gear.json`（21 条）+ `assets/img/gear/` 图标（槽位前缀+序号命名，避免中文名 ASCII 化互撞）。

## 模块间关系

- 爬虫（crawler）只生产数据，不知道前端存在；前端只消费 JSON，不直接访问 wiki。
- `data/raw/企业.html` 是人工保存的渲染页快照，作为"页面实际长什么样"的 ground truth（配装、立绘文件名均由它核实）。
- 批量生成路线：详情页模板化 → 循环 ships.json 662 条 → 每舰一个静态页（已知缺口：各舰立绘/换装文件名与评语需按"渲染页引用为准"的铁律逐一核实）。
