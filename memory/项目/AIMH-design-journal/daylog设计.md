---
title: daylog 设计
summary: daylog（每日日志）机制定稿——单一日志事件流 + AI 零路由写入 + 脚本机械派生主题视图 + 事件/作品双轨边界。
tags: [ daylog, 事件流, 知识体, 派生视图, 机械写入, CEMA, 设计定稿 ]
linked: [ 项目/AIMH-design-journal/SCHEMA, 项目/AIMH-design-journal/什么是AIMH系统, 项目/AIMH/daylog设计路线分歧 ]
person: []
event_date: —
location: []
topic: [{"daylog 设计": ["daylog", "事件流", "beat", "派生视图", "主题索引"]}]
anchors:
  - Chapter: "总纲"
    about: "daylog 是唯一事件流权威源；AI 只 append + 打标签；主题视图全部由脚本派生；建包是唯一路由判断且显式确认。"
    keywords: ["daylog", "事件流", "零路由", "派生", "总纲"]
  - Chapter: "双轨判据：事件流与知识体"
    about: "内容是\"发生过的事\"进 daylog（冻结），是\"会被改写的作品\"进主题包（活文档）；主题隔离为知识体存在，不为事件存在。"
    keywords: ["事件流", "知识体", "双轨", "判据", "主题隔离"]
  - Chapter: "daylog 文件规范"
    about: "每天一份，文件名 daylog-YYYY-MM-DD.md，namespace 固定 日志/；event_date 填当天日期（区别于概念文档的 —）。正文只含一个 ## 流水 节，每条记录是一个 beat 块（### NN·标题·HH:MM + touched + 正文 + beat 注释）。"
    keywords: ["daylog文件规范", "daylog-YYYY-MM-DD", "日志namespace", "流水节", "beat块", "event_date当天"]
  - Chapter: "NN · 一句标题 · HH:MM"
    about: "beat 块结构：### NN·一句标题·HH:MM 标题行，下接 touched（本次实际碰过的文件，AI 显式传入脚本校验）、正文（事实/决策/改动详写）、beat 注释（linked 关联包 + tags 主题词）。NN 两位序号当天自增、HH:MM 脚本落、touched 由 AI 传、linked/tags AI 打标。"
    keywords: ["beat块结构", "NN序号", "HHMM时间戳", "touched", "linked", "tags", "beat注释"]
  - Chapter: "写入协议"
    about: "AI 唯一动作是 append 当天 daylog；序号/时间戳/front-matter 由脚本落；touched 由 AI 显式传入脚本校验；linked/tags 由 AI 写入时打标。"
    keywords: ["写入协议", "append", "touched", "beat", "脚本"]
  - Chapter: "派生视图"
    about: "脚本扫 daylog 的 beat 标记按 linked 聚合，重新生成各包开发日志.md 与全局主题索引；派生物可随时重建、禁止手改。"
    keywords: ["派生视图", "主题索引", "开发日志", "rebuild", "脚本"]
  - Chapter: "起包规则"
    about: "一次性内容永久留 daylog；主题持续积累才经显式触发建新包；旧条目不回搬；脚本做同标签跨 N 天的起包建议。"
    keywords: ["起包", "新建包", "显式触发", "aimh-intake", "提醒"]
  - Chapter: "与既有部件的关系"
    about: "daylog 机制与既有技能/脚本的关系：aimh-daylog-archive 职责取消改写为规范说明；aimh-ingest/aimh-intake/aimh-recall 不动（与事件流正交）；rebuild_index 新增 derive_topic_views 派生步骤，与锚点派生、目录树同管线。"
    keywords: ["aimh-daylog-archive", "aimh-ingest", "aimh-intake", "aimh-recall", "rebuild_index", "derive_topic_views", "正交"]
  - Chapter: "迁移"
    about: "迁移步骤：把现有 项目/AIMH/开发日志.md 的手写详实内容按日期回搬进对应 daylog 的 beat 块（一次性逐日确认）→ 回搬完成后开发日志.md 转纯派生（脚本重新生成）→ 此后详实内容只写 daylog。"
    keywords: ["迁移", "开发日志.md回搬", "beat块", "纯派生", "逐日确认"]
  - Chapter: "开放问题"
    about: "开放问题：beat 块锚点 keywords 5 维契约对小条目偏严，daylog 锚点主要靠 Chapter+about 召回、keywords 允许从简；主题索引.md 规模随 daylog 数量线性涨，需要时再考虑按季度切分。"
    keywords: ["开放问题", "5维偏严", "keywords从简", "主题索引规模", "季度切分"]
pkage_created: 2026-08-15
pkage_updated: 2026-08-29
---

# daylog 设计

> 本文是 daylog 机制的定稿，取代路线分歧阶段的讨论（分歧始末见 `项目/AIMH/daylog设计路线分歧`）。

## 总纲

1. **daylog 是唯一的事件流权威源**：每天一份 `memory/日志/daylog-YYYY-MM-DD.md`，当天发生的事（决策、改动、踩坑、讨论经过）详实内容只写在这里。
2. **AI 写入零路由**：AI 对日志永远只做一件事——向今天的 daylog 追加一条 beat。不做"归到哪个项目/模块"的判断。
3. **主题视图全部派生**：按主题浏览的需求由脚本扫 beat 标记机械聚合满足，派生物随时可重建、不可手改。
4. **建包是唯一的路由判断**：它罕见、显式、需用户确认，不是批量自动流程。

## 双轨判据：事件流与知识体

所有内容先过一道二分：

| | 事件流（daylog） | 知识体（主题包） |
|---|---|---|
| 装什么 | 发生过的事：拍板、踩坑、讨论经过 | 会被改写的作品：随笔正文、角色档案、SCHEMA、约定、架构 |
| 写操作 | 只增不改（追加即冻结） | 可改写、持续维护 |
| 权威于 | 过程（当时怎么发生的） | 结论（这个东西现在长什么样） |

判据一句话：**这条内容是"发生过的事"还是"会被改写的作品"？**

- 主题隔离为知识体而存在，不为事件存在。纯日志类内容不需要主题包，派生视图即够。
- 同一话题两侧各有一份不算漂移：daylog 权威于过程、包权威于结论，各司其职（类比 git：提交历史不改、工作区常新）。
- 事件沉淀为作品时，作品经收录流程另起权威副本，daylog 原始记录原地不动，留 beat `linked` 指向作品。

## daylog 文件规范

每天一份，文件名 `daylog-YYYY-MM-DD.md`，namespace 固定 `日志/`。front-matter 遵循 SCHEMA FM-V2，daylog 特例：`event_date` 填当天日期（区别于概念文档的 `"—"`）。

正文只含一个 `## 流水` 节，其下每条记录是一个 **beat 块**：

```
### NN · 一句标题 · HH:MM
- touched: [相对路径1, 相对路径2]
正文（事实/决策/改动，详写，可有多行与列表）
<!--beat linked:包/文件 tags:词1,词2-->
```

- `NN`：两位序号，当天内自增（01、02…），追加时由脚本扫描现有最大序号 +1。
- `HH:MM`：24 小时制时间戳，脚本落，AI 不填。
- `touched`：本次实际碰过的文件（记忆包或代码文件均可），AI 追加时显式传入，脚本校验存在性（不存在仅告警不拦）。
- `linked`：本条内容关联的记忆包/文件，AI 写入时顺手打标，可为空。
- `tags`：主题词，供派生聚合与起包提醒，AI 打标，可为空。
- beat 用 `###` 标题是为了让 `derive_anchors`/`read_section` 能按节定位与召回，回跳锚点即 `daylog-YYYY-MM-DD#NN`。

## 写入协议

AI 与脚本职责切分：

| 职责 | 谁做 |
|---|---|
| 正文写作（事实/决策/改动） | AI |
| `touched` 内容 | AI 显式传入（事实观察，非路由判断） |
| `linked` / `tags` 打标 | AI（廉价、错了代价低、可事后改） |
| 文件创建（含 FM-V2 骨架） | 脚本 |
| 序号自增、时间戳 | 脚本 |
| touched 存在性校验 | 脚本 |
| 归置/路由判断 | **没有人做**（不存在这一步） |

落地为 `scripts/core/daylog_append.py`：

```
python daylog_append.py --title "修了 query_anchors 中文参数" \
  --touched "hma/server.py,hma/hma_core.py" \
  --linked "项目/AIMH/开发日志" --tags "读取链路,MCP" \
  --body-file 正文.md        # 或 stdin
```

行为：当天 daylog 不存在则按模板新建 → 扫描最大序号 → 追加 beat 块（脚本拼序号/时间戳/beat 注释）→ 校验 touched → 输出追加结果。AI 不经手 front-matter，daylog 的 FM 字段由脚本维护，`pkage_updated` 每次追加自动刷。

行为：当天 daylog 不存在则按模板新建 → 扫描最大序号 → 追加 beat 块（脚本拼序号/时间戳/beat 注释）→ 校验 touched → 输出追加结果。AI 不经手 front-matter，daylog 的 FM 字段由脚本维护，`pkage_updated` 每次追加自动刷。

## daylog FM 规矩（2026-08-29 定稿）

动机：daylog-08-13 曾积累 29 个泛标签，在规模压测中劫持了 daylog设计 的查询（泛词 TAG_EXACT 叠加压过源包）——tags 词袋化是真实召回事故源；而 daylog-08-15 的范本证明 topic 四要素填实质主题是 daylog 可按主题召回的关键。四条规矩：

1. **tags 恒有固定底座 `[daylog, YYYY-MM-DD]`**：beat 主题词走 beat 标记与 `--topic`，绝不进 FM tags 堆积；追加时脚本机械强制——底座缺失自动补，总数超 9 个自动修剪（保留底座 + 前 5 个其余词）。
2. **topic 两阶段**：落库时 `--topic "规范名|变体1,变体2"` 可选——当天主题已知就填（如 08-15 的「读取链路接线」）；未填留 `[]`（不编造）。
3. **topic 合并去重**：同日多 beat 带不同 `--topic` → 按规范名去重合并为多主题日（列表承载，合法形态）；同规范名变体取并集。
4. **治理兜底**：存量空 topic 的 daylog 由蒸馏/对齐补齐（08-15 为范本；08-27 空壳无内容诚实保留）。

落地：`daylog_append.py --topic`（可重复）+ 追加时的 topic 合并与 tags 底座强制。规模基准（`什么是AIMH系统.md` §九）在 daylog 三包对齐后两级/全局均 100%@5。

## 派生视图

`scripts/core/derive_topic_views.py`，纯正则零 AI，挂进 `rebuild_index.py` 管线（一键更新记忆索引.exe 顺带完成）：

1. 扫 `memory/日志/daylog-*.md`，解析全部 beat 块（标题/时间/touched/正文首句/linked/tags）。
2. 按 `linked` 目标聚合，**重新生成**目标包的 `开发日志.md`：
   - 文件头固定一行：`> 本文件由脚本派生，手改会被覆盖。详实内容在各日 daylog。`
   - 每条一行：`- YYYY-MM-DD · HH:MM · 标题 —— 首句摘要 → daylog-YYYY-MM-DD#NN`
   - front-matter 由脚本按 FM-V2 生成，linked 回指各 daylog。
3. 生成全局 `memory/日志/主题索引.md`：按 tags/linked 双维度聚合全部 beat，作为"按主题浏览"的总入口。
4. 起包提醒：统计每个 tag 出现的**不同日期数**，≥3 天即在 主题索引.md 顶部列出"建议：主题 X 已出现 N 天，可考虑起包"。建议由脚本给，决定由用户做。

派生物的两条硬约束：
- **安全闸**：只重写"不存在"或"首部含派生标记（`本文件由脚本派生`）"的文件；已存在的手写文件一律跳过并告警，绝不覆盖。
- **不入索引**：派生视图（开发日志.md / 主题索引.md）不参与 rebuild 索引——它们是聚合视图而非权威源，入索引会让召回命中索引而非源头（`rebuild_all` 扫文件时按标记跳过）。

## 起包规则

- **一次性内容永久留 daylog**：锚点照常召回，无需搬家。召回跨所有 .md 扫锚点，与文件位置无关。
- **持续积累的主题才起包**：触发是显式动作（用户说"收一下/存一下"）→ `aimh-intake` 判型 → 与用户确认落点 → 建新包。
- **旧条目不回搬**：起包前的 daylog 记录原地不动；此后新 beat 的 `linked` 改指新包，派生视图自动把新旧聚合到一起。
- 项目包骨架：`aimh-project` 预建 4 个状态模块（需求清单/项目结构/约定/架构）；`开发日志.md` 不预建，由派生脚本在首次有 beat 指向该包时生成。

## 与既有部件的关系

- `aimh-daylog-archive` 技能：原"AI 夜间读目录树自主归位"职责取消，技能改写为 daylog 写入与派生规范的说明（何时 append、何时跑派生、起包怎么触发）。
- `aimh-ingest` / `aimh-intake`：不动。它们是"作品/知识"的收录入口，与 daylog 事件流正交。
- `aimh-recall`：不动。召回不依赖 daylog 与派生视图的区分。
- `rebuild_index.py` / 一键更新记忆索引.exe：新增派生步骤（derive_topic_views），与锚点派生、目录结构树同管线。

## 迁移

现状里 `项目/AIMH/开发日志.md` 存着手写详实内容（如 2026-08-15 的 D1/D2/D3），是按旧分工"daylog 索引 + 开发日志详写"落的。迁移步骤：

1. 把现有手写详实内容按日期回搬进对应 daylog 的 beat 块（一次性，需逐日确认）。
2. 回搬完成并确认无遗漏后，开发日志.md 转纯派生（脚本重新生成）。
3. 此后详实内容只写 daylog。

## 开放问题

- beat 块的锚点 keywords 5 维契约对小条目偏严，daylog 锚点主要靠 Chapter+about 召回，keywords 允许从简。
- 主题索引.md 的规模随 daylog 数量线性涨，需要时再考虑按季度切分。
