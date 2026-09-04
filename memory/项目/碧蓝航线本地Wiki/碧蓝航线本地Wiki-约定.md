---
title: 碧蓝航线本地Wiki 约定
summary: blhx-wiki 的死规矩。最重铁律：BWIKI 是 9 年屎山，一切内容以页面实际渲染引用为准、绝不认文件名（企业.jpg 同人图事故）；爬虫必须礼貌限速、突发请求会触发 WAF HTTP 567；前端为 Apple 官网风格、明确拒绝玻璃拟态与粒子背景；入场揭幕必须多路径兜底、初始隐藏 CSS 挂 html.js 门控。
tags: ["project", "碧蓝航线本地Wiki", "铁律协作"]
linked: ["项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-需求清单.md", "项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-项目结构.md", "项目/碧蓝航线本地Wiki/碧蓝航线本地Wiki-架构.md"]
person: [{"用户": ["我", "用户本人"]}]
event_date: "—"
location: []
topic: [{"碧蓝航线本地Wiki": ["blhx-wiki", "铁律协作", "规矩约定"]}, {"BWIKI": ["biligame", "屎山内容"]}]
anchors:
  - Chapter: "BWIKI数据可信度铁律"
    about: "9 年老 wiki 堆积大量误导性内容：文件名叫'企业'的图实为同人图、且 文件:企业.jpg 在 wiki 上根本不存在；信息框实际引用 文件:企业立绘.jpg。收录任何图片/字段前必须核对渲染页 HTML 的实际引用，每张镜像图记录来源 URL。"
    keywords: ["2026-09-01", "BWIKI站点", "立绘事故", "企业立绘.jpg", "用户"]
  - Chapter: "爬虫礼貌与限流"
    about: "api.php 抓取必须限速 0.20-0.34s+抖动、UA 标明个人镜像用途、磁盘缓存断点续爬；突发请求触发 biligame WAF（HTTP 567/断连），需等冷却；patchwiki 图片 CDN 与 api.php 限流相互独立，已知 URL 可直接下载；MediaWiki 缩略图不能放大（原图 350px 请求更大尺寸即 404）。"
    keywords: ["2026-09-01", "api.php接口", "限速爬取", "crawl_report", "用户"]
  - Chapter: "前端设计红线"
    about: "设计基调 Apple 官网式高大上现代感+滚动叙事，明确拒绝'AI味'玻璃拟态+粒子背景；动效只用 transform/opacity；必须尊重 prefers-reduced-motion；数字统一 .num tabular-nums 防计数抖动；配装推荐等展示内容最小三要素=基础信息/技能介绍/装备搭配推荐。"
    keywords: ["2026-09-01", "app前端", "滚动叙事", "base.css", "用户"]
  - Chapter: "入场动画兜底铁律"
    about: "首屏揭幕绝不允许只依赖单一 async 路径：必须 complete 快路径 + decode + load/error 事件 + 硬超时（900ms）多路径兜底，once-guard 防重入；所有'初始隐藏'CSS 挂在 html.js 门控下（ship.js 首行打类），JS 失效时页面退化为静态可见而非永久空白。"
    keywords: ["2026-09-01", "app前端", "渐进增强", "ship.js", "用户"]
pkage_created: 2026-09-02
pkage_updated: 2026-09-02
---

# 碧蓝航线本地Wiki 约定

## 铁律（不可违反）

- **BWIKI 数据可信度**：一切以页面实际渲染引用为准，绝不认文件名。教训：hero 曾用一张同人图（文件名叫"企业"），而 `文件:企业.jpg` 在 wiki 上根本不存在；信息框真实引用是 `文件:企业立绘.jpg`。收录前核对渲染页 HTML，镜像图必须记录来源 URL（见 项目结构.md 镜像资产清单）。
- **爬虫礼貌**：请求间隔 0.20-0.34s + 抖动；UA 标明 personal local mirror；已缓存页面跳过（重跑即断点续爬）。突发请求会触发 biligame WAF（HTTP 567 / RemoteDisconnected），被限后停手等冷却，不要重试轰炸。
- **前端设计红线**：Apple 官网风格（高大上、现代感、滚动叙事动画）；**明确拒绝"AI味"的玻璃拟态 + 粒子背景**（用户明令）。动效只用 transform/opacity，尊重 prefers-reduced-motion。
- **入场动画兜底**：揭幕多路径（complete/decode/load+error/900ms 硬超时），初始隐藏 CSS 挂 `html.js` 门控；任何环境下首屏黑屏不得超过 0.9s。
- **背景图使用**：wiki 图片做背景一律 blur+压暗+mask 渐隐（氛围层），不整张贴原图；350px 小图只许重度模糊使用。

## 协作约定

- 预览方式：`cd app && python -m http.server 8788` → http://localhost:8788；自动化浏览器跨调用重激活会把滚动条重置回顶部（测试环境表象，非页面 bug），逐区块验证须在单次调用内完成滚动+截图。
- 展示内容最小三要素：**基础信息、技能介绍、装备搭配推荐**（用户钦定，配装推荐区块由此而来）。
- 数字类内容全部挂 `.num`（tabular-nums），滚动计数时不抖动。
- 配装推荐语义照搬 wiki 原版：按优先级自上而下，有啥用啥；同行定位相同时右边可能略强。
