---
title: 碧蓝航线本地Wiki 项目结构
summary: blhx-wiki 的目录与文件布局。三层结构：crawler/（爬虫与解析）、data/（raw wikitext 缓存 + 规范化 JSON + demo 生成脚本）、app/（零依赖静态前端：详情页 + css + js + 镜像资产）。项目根另有 AIMH.md 进度快照。
tags: ["project", "碧蓝航线本地Wiki", "目录布局"]
linked: ["项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-需求清单.md", "项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-约定.md", "项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-架构.md"]
person: [{"用户": ["我", "用户本人"]}]
event_date: "2026-09-01"
location: []
topic: [{"碧蓝航线本地Wiki": ["blhx-wiki", "目录布局", "结构总览"]}]
anchors:
  - Chapter: "数据层目录"
    about: "crawler/crawl_blhx.py（api.php 抓取+模板解析）；data/raw/ships|equip/（wikitext 磁盘缓存）与 data/raw/企业.html（渲染页快照，配装推荐与图片 URL 的 ground truth）；data/ships.json(662条)、equipment.json(792条)、make_demo.py（生成 app/data/enterprise.json 含威胁矩阵）、crawl_report.txt。"
    keywords: ["2026-09-01", "data目录", "wikitext抓取", "crawl_blhx.py", "用户"]
  - Chapter: "前端层目录"
    about: "app/index.html（企业号详情页，手写静态样品）；app/css/base.css（设计令牌+reveal 基元）与 ship.css（组件+区块样式）；app/js/ship.js（零依赖动效引擎：揭幕/浮现/计数/视差/scrollspy）；app/data/enterprise.json 与 enterprise_gear.json（页面数据）。"
    keywords: ["2026-09-01", "app目录", "静态详情页", "ship.js", "用户"]
  - Chapter: "镜像资产清单"
    about: "app/assets/img/ 下全部镜像图及出处：enterprise.jpg=文件:企业立绘.jpg(patchwiki a/a2)、enterprise-chibi.jpg=文件:企业头像.jpg(6/61)、bg-pledge.jpg=文件:企业誓约.jpg(9/90, 350px)、bg-anniv.jpg=文件:企业换装3.jpg(b/b1, 350px)、gear/ 21 个装备图标（f/b/t/d/s 前缀+序号命名）。"
    keywords: ["2026-09-02", "assets目录", "立绘镜像", "enterprise.jpg", "用户"]
pkage_created: 2026-09-02
pkage_updated: 2026-09-02
---

# 碧蓝航线本地Wiki 项目结构

## 目录布局

```
blhx-wiki/
├── AIMH.md                      # 项目进度快照（含资产出处清单）
├── crawler/
│   └── crawl_blhx.py            # api.php 抓取 + 模板解析（纯标准库、限速、断点续爬）
├── data/
│   ├── raw/
│   │   ├── ships/               # 686 个舰娘页 wikitext 缓存（含 企业.wikitext）
│   │   ├── equip/               # 893 个装备页 wikitext 缓存
│   │   └── 企业.html            # 企业渲染页快照（配装推荐/图片URL 的 ground truth）
│   ├── ships.json               # 662 条舰娘规范化参数（无损 params + core 提取）
│   ├── equipment.json           # 792 条装备规范化参数（含 对甲比例/弹药/伤害）
│   ├── make_demo.py             # 企业 demo 数据生成（含威胁矩阵统计）
│   └── crawl_report.txt         # 爬取报告
└── app/                         # 预览：cd app && python -m http.server 8788
    ├── index.html               # 企业号(NO.077)详情页（手写静态样品）
    ├── css/
    │   ├── base.css             # 设计令牌 + .reveal 基元 + reduced-motion
    │   └── ship.css             # 导航/hero/各区块/配装/页脚样式 + 响应式
    ├── js/
    │   └── ship.js              # 零依赖动效引擎（揭幕/浮现/计数/视差/scrollspy）
    ├── data/
    │   ├── enterprise.json      # 企业核心/属性/技能/装备槽/评价/威胁矩阵
    │   └── enterprise_gear.json # 配装推荐（攻略组认证，21 条带图标路径）
    └── assets/img/
        ├── enterprise.jpg       # 官方立绘（镜像自 BWIKI）
        ├── enterprise-chibi.jpg # 官方头像
        ├── bg-pledge.jpg        # 誓约图（评价区氛围层）
        ├── bg-anniv.jpg         # 换装3（配装区氛围层）
        └── gear/                # 21 个装备图标（f/b/t/d/s 前缀+序号）
```

> 本文件只装结构。铁律/约定/架构决策进 约定.md / 架构.md。
