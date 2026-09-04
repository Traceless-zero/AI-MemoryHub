---
title: 碧蓝航线本地Wiki 需求清单
summary: 碧蓝航线本地Wiki（blhx-wiki）的需求清单与 roadmap。已完成：BWIKI 全量爬取（686 舰娘 / 893 装备 wikitext）、企业号(NO.077)详情页样品（含数据/装甲/技能/装备槽/配装推荐/评价区块）、hero 入场动画修复、官方立绘替换、锚点导航。未完成：数据驱动渲染批量生成 662 舰娘页、图鉴索引页、装备详情页。
tags: ["project", "碧蓝航线本地Wiki", "需求待办"]
linked: ["项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-项目结构.md", "项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-约定.md", "项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-架构.md"]
person: [{"用户": ["我", "用户本人"]}]
event_date: "2026-09-01"
location: []
topic: [{"碧蓝航线本地Wiki": ["blhx-wiki", "本地镜像", "roadmap"]}, {"BWIKI": ["biligame", "wiki.biligame.com"]}, {"企业号": ["企业", "USS Enterprise", "CV-6", "NO.077"]}]
anchors:
  - Chapter: "已完成里程碑"
    about: "截至 2026-09-01 已完成：crawl_blhx.py 全量抓取 686 舰娘与 893 装备 wikitext 并规范化为 ships.json(662条含装甲类型652)与 equipment.json(792条含对甲比例322)；企业号详情页样品建成；hero 入场动画 decode 挂起 bug 修复；官方立绘替换同人图；配装推荐区块；锚点导航 scrollspy。"
    keywords: ["2026-09-01", "blhx-wiki目录", "全量爬取", "ships.json", "用户"]
  - Chapter: "待办路线图"
    about: "未完成需求：把硬编码详情页改成读 app/data/*.json 的数据驱动渲染并批量生成全部 662 舰娘页；图鉴索引页；装备详情页；等 api.php 限流解禁找高清背景大图；威胁矩阵扩到通常/声导/触发式/半穿甲等 7 种弹种；equip 组补抓 79 个失败页。"
    keywords: ["2026-09-02", "memory目录", "批量生成", "enterprise_gear.json", "用户"]
pkage_created: 2026-09-02
pkage_updated: 2026-09-02
---

# 碧蓝航线本地Wiki 需求清单

项目目标：爬取 BWIKI（wiki.biligame.com/blhx）的 api.php 结构化数据，做纯静态本地 wiki。
设计基调：Apple 官网式排版与滚动叙事动画。

## 已完成

- [x] 爬虫 `crawler/crawl_blhx.py` 全量抓取：Category:舰娘 686 页、Category:装备 893 页 wikitext，磁盘缓存可断点续爬（完成于 2026-09-01）
- [x] 规范化落盘 `data/ships.json`（662 条，含装甲类型 652 条）与 `data/equipment.json`（792 条，含对甲比例 322 条）（完成于 2026-09-01）
- [x] 企业号(NO.077)详情页样品 `app/index.html`：hero / 数据 / 装甲矩阵 / 技能 / 装备槽 / 评价区块（完成于 2026-09-01）
- [x] hero 入场动画 bug 修复：decode 挂起或 ship.js 未执行导致首屏永久空白 → 多路径兜底揭幕 + html.js 门控渐进增强（完成于 2026-09-01）
- [x] 立绘数据可信度修正：替换同人图为官方 `文件:企业立绘.jpg`（1000×1500）与 `文件:企业头像.jpg`（完成于 2026-09-01）
- [x] 配装推荐区块（最小三要素之装备搭配推荐）：解析 wiki 渲染页「配装推荐」模块（攻略组认证），结构化为 `app/data/enterprise_gear.json` + 21 个装备图标镜像（完成于 2026-09-01）
- [x] 页面背景去纯黑：官方立绘重度模糊氛围层（hero wash / 配装区 wash / 评价区誓约 wash）（完成于 2026-09-01）
- [x] 锚点导航：nav 六锚点 + scrollspy 高亮 + scroll-margin-top 防遮挡（完成于 2026-09-01）
- [x] 项目进度快照存档 `blhx-wiki/AIMH.md`（完成于 2026-09-01）

## 未完成

- [ ] 详情页改为读 `app/data/*.json` 数据驱动渲染，随后批量生成全部 662 舰娘页
- [ ] 图鉴索引页（ships.json 已有全部核心字段）
- [ ] 装备详情页（equipment.json 含对甲比例/弹药/伤害）
- [ ] 高清背景图：api.php 限流解禁后查 `文件:企业誓约.jpg` 原图与活动横幅大图（现有誓约/换装图仅 350px，只够重度模糊用）
- [ ] 威胁矩阵扩弹种：enterprise.json 已含 7 种（通常/声导/触发式/半穿甲等），页面只展示炮雷 3 种
- [ ] equip 组补抓：893 页中 79 个失败（crawl_report.txt 记录）
