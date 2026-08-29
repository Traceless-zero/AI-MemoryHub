---
title: index.db 存储规格
summary: AIMH 统一前台索引（memory/index.db）的表结构、字段来源、版本迁移与重建维护说明。
tags: [ 索引, 存储, 引擎, 规格, index ]
linked: [ 项目/AIMH-design-journal/SCHEMA.md ]
person: []
event_date: —
location: []
topic: [{"索引规格": ["index.db", "SQLite", "字段来源", "重建维护"]}]
anchors:
  - Chapter: "1. 定位"
    about: "index.db 是仓库根下唯一的 SQLite 统一前台索引，落地 CEMA 前后台严格一一对应铁律，纯派生缓存可由 front-matter 无损重建，本身不存放唯一真相。"
    keywords: ["index.db", "统一前台索引", "SQLite", "CEMA", "派生缓存"]
  - Chapter: "2. 物理与生命周期"
    about: "路径 memory/index.db，主键为 package_id 与 filepath 组合，filepath 是 .md 绝对路径，package_id 是相对仓库根的正斜杠路径。"
    keywords: ["memory/index.db", "主键", "package_id", "filepath"]
  - Chapter: "3. 表结构（`events`）"
    about: "events 表列定义：package_id/filepath 双主键，title/summary/tags/linked/anchors 四要素(person/event_date/location/topic) 等；embedding 列预留向量位当前未启用；辅助索引 idx_pkg ON events(package_id)、idx_tags ON events(tags) 加速按包/标签查询。"
    keywords: ["events表", "双主键", "package_id", "filepath", "embedding预留", "idx_pkg", "idx_tags"]
  - Chapter: "4. 字段来源映射（front-matter → 列）"
    about: "front-matter → 列 映射规则：首级括号一律 [ ]、字段顺序固定（title→summary→tags→linked→person→event_date→location→topic→anchors→pkage_created→pkage_updated）、event_date 无时间写哨兵 —、linked 用复合 id；各列来源表（title/summary/tags/linked/anchors/四要素/pkage_* 各自映射形态）。"
    keywords: ["字段映射", "首级括号", "字段顺序", "哨兵—", "复合id", "来源表"]
  - Chapter: "5. 派生与遗留字段处理（V2）"
    about: "V2 极简字段集：旧字段 id/aliases/features 不再单独成列——id 改由 filepath stem 即时派生、aliases/features 改由四要素「规范名+变体」读取时合成；四要素在 front-matter 写作 [{规范名:[变体]}]，写入归一 JSON 字典、读取还原；旧式 aliases/features 在 rebuild 时经 _merge_legacy 折叠进四要素，数据不丢。"
    keywords: ["V2极简", "id派生", "aliases折叠", "features合成", "_merge_legacy", "四要素归一"]
  - Chapter: "6. 重建与维护"
    about: "rebuild_all 清库重扫 front-matter 重插，install 与 uninstall 单包装卸，front-matter 是唯一真相，旧表检测到即原地迁移。"
    keywords: ["rebuild_all", "重建", "install", "迁移"]
  - Chapter: "7. 检索如何消费本索引"
    about: "query_anchors 用 anchors 做 C+A 选章、features 两跳缩圈、BM25 重排，四要素用于 rerank 软加权与拒答 Gate，全确定性零 ML。"
    keywords: ["query_anchors", "C+A 选章", "features 两跳", "BM25 重排", "拒答 Gate"]
pkage_created: 2026-08-12
pkage_updated: 2026-08-29
---

# index.db 存储规格（AIMH 统一前台索引）

> 本文件自身的 front-matter 即按「最新规范」书写：首级括号一律 `[ ]`、字段顺序固定
> （title → summary → tags → linked → person → event_date → location → topic → anchors →
> pkage_created → pkage_updated）、`event_date` 无时间信息写哨兵串 `"—"`（区别于 `pkage_created`）、字符串按 JSON 要求加双引号。
> 四要素写作 `[{规范名:[变体]}, …]`（首级 `[ ]`，每项一个 `{规范名:[变体]}` 字典）。

## 1. 定位

`memory/index.db` 是 AIMH 仓库根下**唯一**的 SQLite 统一前台索引，落地 CEMA「前后台严格 1:1 铁律」：

- 每个事件包对应索引里**恰好一条记录**；`package_id` 列区分「属于哪个包」。
- 它是**纯派生缓存**——全部内容都可由各包 `.md` 的 front-matter **无损重建**，本身不存放唯一真相。
- 真相唯一来源是 `.md` 文件的 front-matter；索引只是为检索加速而存在的物化视图。

## 2. 物理与生命周期

- 路径：`memory/index.db`（单文件，SQLite）。
- 主键：`(package_id, filepath)`。
  - `filepath` = 包内 `.md` 的 OS 原生绝对路径（真实文件路径，非逻辑 id）。
  - `package_id` = 包目录相对仓库根的路径（正斜杠分隔，如 `原创角色/demo-char`）。
- 重建：`Memory.rebuild_all()` 清库后逐包重扫 front-matter 重插。索引损坏 = 重新扫描，不丢数据。

## 3. 表结构（`events`）

| 列 | 类型 | 含义 |
|---|---|---|
| `package_id` | TEXT | 包标识（相对仓库根路径，正斜杠）【主键】 |
| `title` | TEXT | 人类可读标题 |
| `summary` | TEXT | 富叙述摘要（描述包「现在是什么」） |
| `tags` | TEXT | 分类标签，JSON 数组 |
| `linked` | TEXT | 关联包复合 id 列表，JSON 数组 |
| `filepath` | TEXT | `.md` 绝对路径【主键】 |
| `pkage_created` | TEXT | 包创建时间（收录时间） |
| `pkage_updated` | TEXT | 包更新时间 |
| `embedding` | BLOB | 预留向量位（当前未启用，保持表结构稳定） |
| `anchors` | TEXT | 章节锚点，JSON 数组 `[{Chapter, about, keywords}]` |
| `person` | TEXT | 人物四要素，归一化 JSON 字典 `{规范名:[变体]}` |
| `event_date` | TEXT | 时间四要素（如 `1969-2012`） |
| `location` | TEXT | 地点四要素，归一化 JSON 字典 `{规范名:[变体]}` |
| `topic` | TEXT | 主题四要素，归一化 JSON 字典 `{规范名:[变体]}` |

辅助索引：`idx_pkg ON events(package_id)`、`idx_tags ON events(tags)`。

## 4. 字段来源映射（front-matter → 列）

front-matter 字段书写规则（最新规范）：

- **首级括号一律 `[ ]`**：列表型字段（tags / linked / anchors / 四要素的每项）以 `[ ]` 包裹；四要素的每个「规范名→变体」是一个 `{规范名:[变体]}` 字典，整体再包进 `[ ]`，即写作 `[{规范名:[变体]}, …]`。字符串按 JSON 要求加双引号（引擎 `json.loads` 解析通道需要，与 anchors 同源）。
- **字段顺序固定**：`title → summary → tags → linked → person → event_date → location → topic → anchors → pkage_created → pkage_updated`。
- **`event_date` 无时间信息写哨兵串 `"—"`**：包无独立故事/事件时间（如概念/设计/OC 背景）时写 `"—"`，明确区别于 `pkage_created` 收录时间（召回不注入时间信号）；有具体时间信息（单点 `YYYY-MM-DD` 或区间 `YYYY-YYYY`）再填充。
- **`linked` 用复合 id**：必须写「相对路径 + .md」的复合键（含目录与文件名），不再用裸文件名，例如 `[原创角色/示例角色/demo-base.md]`。

| 列 | 来源 front-matter 字段 | 存储形态 |
|---|---|---|
| `title` | `title` | 原值 |
| `summary` | `summary` | 原值 |
| `tags` | `tags` | JSON 数组（如 `[索引, 存储, 引擎, 规格, index]`） |
| `linked` | `linked` | JSON 数组（复合 id，如 `["项目/AIMH-design-journal/SCHEMA.md"]`） |
| `anchors` | `anchors` | JSON 数组 `[{Chapter, about, keywords}]`，pageIndex 模型：选分只看 `Chapter`+`about`+`keywords`，正文由 `Chapter` 回读 |
| `person` | `person` | front-matter 写作 `[{规范名:[变体]}, …]`；列存归一化 JSON 字典 `{规范名:[变体]}` |
| `location` | `location` | 同上（首级 `[ ]`，每项 `{规范名:[变体]}`） |
| `topic` | `topic` | 同上；`topic` 的变体数组里纯年份/日期元素即该事件发生时间 |
| `event_date` | `event_date` | 字符串；无时间信息写哨兵串 `"—"`，有具体时间信息再填（区别于 `pkage_created`） |
| `pkage_created` | `created` | 旧字段改名继承 |
| `pkage_updated` | `updated` | 旧字段改名继承 |
| `package_id` | 包目录推导 | 非 front-matter，由目录结构得出 |
| `filepath` | 文件本身 | 非 front-matter，由 `.md` 路径得出 |

front-matter 字段的权威写法见 `SCHEMA.md`（含「字段齐备性：必现 + 空容器」规则，见 §2.2）。

## 5. 派生与遗留字段处理（V2）

为贴合 V2 极简字段集，以下旧字段**不再单独成列**，改为派生或折叠：

- **`id`**：不再存储。对外契约的「包 id」= 文件名 stem（`filepath` 去扩展名），读取时即时派生；内部检索主键用 `filepath`，对外返回前再转回 stem。
- **`aliases`**：不再存储。`EventPackage.aliases` 是读取时由四要素「规范名 + 变体」合成的属性（含分类标签语义）。
- **`features`**：不再存储。`EventPackage.features` 是读取时由四要素合成的属性；检索的 F 段（`query_features`）直接扫 `person`/`topic`/`location` 字典合并出 fmap。

四要素 `person`/`location`/`topic` 在 front-matter 中写作 `[{规范名:[变体]}, …]`：

- 写入时归一为 JSON 字典 `{规范名:[变体]}`（列存形态）；读取时还原。
- 旧式 `aliases`(列表)/`features`(字典) 在 `rebuild` 时由 `from_markdown` 经 `_merge_legacy` 折叠进四要素字典，数据不丢。

## 6. 重建与维护

- **全量重建**：`Memory(root).rebuild_all()` → `DELETE FROM events` 后逐包重扫 front-matter 重插。幂等，可随时重跑。
- **单包装卸**：`install(pkg_dir)` 装单个包、`uninstall` 卸单个包，只动目标包自己的索引行。
- **真相与缓存**：front-matter 是唯一真相；改了 `.md` 的 front-matter 后重建索引即可，无需手工改 `index.db`。
- **旧库自动迁移**：`_init_db` 打开时若检测到旧表（含 `id`/`aliases`/`features`/`created`/`updated` 列），会建 V2 表、搬运数据（`created`→`pkage_created`、`updated`→`pkage_updated`，缺列 `COALESCE` 兜底）、删旧表、改名。迁移幂等，可重复调用。

## 7. 检索如何消费本索引

`query_anchors`（确定性、零 ML，全部可由 front-matter 重建）：

1. **C+A 选章**：扫 `anchors` 列，用 `Chapter`+`about`+`keywords` 选准章节，正文由 `Chapter` 回读（pageIndex 模型）。
2. **F 段缩圈**：`query_features` 扫 `person`/`topic`/`location` 字典，查询词命中规范名/属性词变体（支持子串如 `回旋镖`⊂`回旋镖计划`）→ 把候选池缩到含该词章节。
3. **BM25 重排**：`_bm25_corpus` 用 `anchors` 的 `body` 拼文档做确定性 BM25 重排。
4. **四要素 rerank + 拒答 Gate**：`person`/`event_date`/`location`/`topic` 用于 post-retrieval 软加权（命中要素数越多越靠前，**不剔除**任何候选）；拒答 Gate 用四要素 + 正文判越界实体（已知实体但召回包内零命中 → 拒答）。

索引的所有统计（IDF、BM25 文档频率）只读 `events` 表、可由 front-matter 随时重建，故不落盘缓存。
