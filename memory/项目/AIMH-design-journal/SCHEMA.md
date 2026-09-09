---
title: AIMH 设计规范（落库与校验唯一真相源）
summary: AIMH 所有 memory 包写入与 lint 校验的权威契约——CEMA 存储、front-matter V2（inline JSON 单行 或 block 换行式 引擎均可正确解析）、四要素、锚点五维、四要素适配器（写时映射/读时加权不门控/跨包查询）、检索三段式、命名空间与拆包契约、lint 契约。
tags: [ schema, 规范, 落库契约, 设计, front-matter-V2 ]
linked: [ 项目/AIMH-design-journal/存储架构总览.md, 项目/AIMH-design-journal/召回消歧管线设计（实现）.md, 项目/AIMH-design-journal/召回消歧的数学与语言哲学思路.md, 项目/AIMH-design-journal/什么是AIMH系统.md ]
person: []
event_date: —
location: []
topic: [{"设计规范": ["FM-V2", "front-matter", "落库契约", "锚点模型"]}]
anchors:
  - Chapter: "1. 存储层契约（CEMA）"
    about: "事件包 = 一个 .md（--- YAML front-matter ＋ ## 标题树正文）＝ 唯一权威源；index.db 是派生薄索引，删了可由全部 .md 的 front-matter 全量重建。零依赖零 ML（hma_core 仅标准库），命名空间目录硬隔离。"
    keywords: ["事件包", "front-matter", "index.db", "派生索引", "零依赖", "零ML", "命名空间", "CEMA"]
  - Chapter: "2. Front-matter V2（落库照抄本节 + §2.8 范本）"
    about: "Front-matter V2 总入口：规定所有包落库照抄本节 + §2.8 范本。总原则含单 --- 包裹、空字段写空容器、四要素必填、变体归一 dict、FM 人工填写铁律（禁机械）、写后回读自检、字段齐备、写入顺序 keyword→归纳→四要素。"
    keywords: ["front-matter-V2", "空容器", "四要素", "变体归一", "人工填写铁律", "写后回读", "字段齐备", "写入顺序"]
  - Chapter: "2.0 总原则"
    about: "front-matter 以单个 --- 包裹、body 为唯一内容源；空字段写空容器不省略；四要素有内容必填；变体归一为「规范名:[变体]」dict 走 json.loads；FM 内容须 AI 逐章语义人工填、禁机械偷懒；写后必须回读自检；写入顺序 keyword 先→理解归纳→四要素。"
    keywords: ["单---包裹", "空容器", "四要素必填", "变体dict", "人工语义填写", "写后回读自检", "keyword先归纳后"]
  - Chapter: "2.1 序列化格式（inline 单行 JSON 或 block 换行式 均可）"
    about: "列表/字典字段可写成 inline 单行 JSON 或 block 换行式，引擎 _parse_fm 已升级为块感知解析器，不再有 block 被静默读丢的坑；推荐 block 换行式人读直观，inline 更紧凑，二者均合规。"
    keywords: ["序列化格式", "inline单行", "block换行式", "块感知解析器", "静默读丢", "to_markdown"]
  - Chapter: "2.2 字段齐备性（11 必填，必须都出现）"
    about: "V2 规定 11 字段（title/summary/tags/linked/anchors/person/event_date/location/topic/pkage_created/pkage_updated）每包必现；无内容写空容器 []/{}，event_date 无时间写哨兵 —，禁止省略整行或写 none/null/\"\"。"
    keywords: ["字段齐备性", "11必填", "空容器", "哨兵—", "禁止none", "禁止省略"]
  - Chapter: "2.3 禁写字段（身份由路径派生 / 折进四要素 / pkage_* 替代）"
    about: "禁写 id（身份＝路径派生复合键）、aliases/features（变体折四要素 dict）、created/updated（统一 pkage_created/pkage_updated）；无内容字段写空容器而非省略。"
    keywords: ["禁写字段", "无id", "aliases折四要素", "pkage_created", "pkage_updated", "空容器"]
  - Chapter: "2.4 四要素（一等字段，有内容必填）"
    about: "四要素是一等字段，有内容必填：person（人物）、event_date（事件时间）、location（地点）、topic（主题）；读取时按命中要素数软加权（person4>time3>loc2>topic1），留空=漏召回。event_date 三种形态：单点 YYYY-MM-DD / 跨度 YYYY-YYYY / 哨兵 —；实体名不进 tags 收进四要素变体 dict。"
    keywords: ["四要素", "person", "event_date", "location", "topic", "一等字段", "必填", "哨兵—"]
  - Chapter: "2.5 包生命周期时间戳"
    about: "pkage_created ＝ 收录时间，重填时保留原值不刷成今天；pkage_updated ＝ 每次文件更新后刷新日期。二者替代旧 created/updated。"
    keywords: ["pkage_created", "pkage_updated", "收录时间", "生命周期", "保留原值"]
  - Chapter: "2.6 linked（复合 id）"
    about: "linked 是关联包相对 memory/ 根的复合 id（含目录＋.md），如 原创角色/示例角色/demo-base.md；不用裸文件名，跨项目同名不歧义；人物文件夹须用全名。"
    keywords: ["linked", "复合id", "相对路径", "跨项目不歧义", "人物全名", "文件夹"]
  - Chapter: "2.7 anchors（唯一形态）"
    about: "anchors 唯一形态 [{Chapter,about,keywords}]；about 自然语言一句短答兼二次消歧；keywords 必写覆盖 5 维（时间/地点/关键事件/锚定物品/人物各≥1 token，缺维漏召回）；扁平 BM25 匹配无选章子系统；别名经四要素变体 dict 解析透传。"
    keywords: ["anchors", "Chapter", "about", "keywords", "5维契约", "扁平BM25", "别名透传"]
  - Chapter: "2.8 标准范本（ block，照抄）"
    about: "§2.8 给出 block 换行式标准范本（title/summary/tags/linked/person/location/topic/anchors 全字段示范），照抄前逐项核对无禁写字段、anchors keywords 必覆盖 5 维、空字段写 []/{}。"
    keywords: ["标准范本", "block示范", "照抄核对", "全字段", "5维必写"]
  - Chapter: "2.9 对话记录 tags 派生与矛盾处理"
    about: "tags 由 ## 关键内容 每条决定抽「决策主语/规范实体」得来，单一真相源不手工另写；矛盾/反向更新引擎只忠实保留相左事实都检索得出，由 AI 理解层判定用哪条，写入绝不静默覆盖旧决定。"
    keywords: ["tags派生", "关键内容", "决策主语", "单一真相源", "矛盾保留", "不静默覆盖"]
  - Chapter: "3. 锚点模型与检索契约（含四要素适配器）"
    about: "锚点三字段（Chapter 定位键/about 短答/keywords 章级词）必写 5 维；三层检索 query()(包级 BM25)→query_anchors()(锚点级)→read_section()(取正文)；字段权重 person4>time3>loc2>topic1；dK 分差裁切（waterfall_cut >75 单向）收束候选，包级 rerank 装置默认关；零 ML 零向量。"
    keywords: ["锚点模型", "三层检索", "query_anchors", "read_section", "字段权重", "dK裁切", "零ML"]
  - Chapter: "3.1 四要素适配器（写时映射 / 读时加权 / 跨包查询）"
    about: "四要素适配器机制：写时把四要素映射到统一字段形态（list[dict] 规范名:[变体]），读时按命中要素数软加权调序（不剔除），跨包查询时按子树收敛候选集。"
    keywords: ["四要素", "适配器", "写时映射", "读时加权", "跨包查询"]
  - Chapter: "4. 命名空间与拆包契约"
    about: "命名空间与拆包总契约：daylog/project/OC/对话/user/其他落点 + 用户五模块 + 项目 README 式功能拆包 + 拆包触发铁律（凝聚性+体积）+ AI 收录路由判定。"
    keywords: ["命名空间", "daylog", "project", "OC", "拆包", "路由", "模块"]
  - Chapter: "4.1 用户数据模块划分（user）"
    about: "用户数据落点 memory/用户/<模块>/，主语必须是用户本人（不进话题类目）；与项目/OC 空间硬隔离。"
    keywords: ["用户数据", "memory/用户", "主语本人", "不进话题", "硬隔离"]
  - Chapter: "4.2 项目工程模块划分（README 式功能拆包）"
    about: "项目工程落点 memory/项目/<项目名>/，仿照普通项目 README 做功能拆包（需求/结构/开发日志/约定各成单独 .md，单一职责），读者视角而非子系统视角。"
    keywords: ["项目工程", "README式拆包", "功能拆包", "读者视角", "单一职责"]
  - Chapter: "4.3 拆包触发铁律：凝聚性 + 体积"
    about: "拆包触发条件是体积/凝聚性，不是作者写法运气；对应设计原则③「活文档整合/无限拆分」。"
    keywords: ["拆包触发", "凝聚性", "体积", "活文档整合", "无限拆分"]
  - Chapter: "4.4 AI 收录时的模块路由判定"
    about: "AI 收录落点决策配合 aimh-ingest 步骤 2 的「一次比对 index」判定该进哪个命名空间/模块；不凭记忆拍板。"
    keywords: ["AI收录", "落点决策", "aimh-ingest", "一次比对index", "路由判定"]
  - Chapter: "5. lint 契约（`scripts/core/lint_memory.py` 检查清单）"
    about: "lint_memory.py 确定性扫描所有 memory/**/*.md 做写前/写后校验：11 字段齐备、无禁写字段、anchors 5 维、四要素变体合法 JSON、空容器规范；与软契约（本文件）＋硬约束（hma_core）构成三层校验。"
    keywords: ["lint_memory", "校验清单", "11字段", "禁写字段", "5维检查", "三层校验"]
  - Chapter: "6. 细则索引（推导 / 哲学 / 实现，非落库契约）"
    about: "§6 指向推导/哲学/实现类细则文档索引（存储架构总览、召回消歧管线、数学与语言哲学思路、什么是AIMH系统等），本文件只写落库与 lint 契约，细则见各文档。"
    keywords: ["细则索引", "推导", "哲学", "实现", "存储架构总览", "召回消歧"]
pkage_created: 2026-08-14
pkage_updated: 2026-09-09
---

# AIMH 设计规范（落库与校验唯一真相源）

> 本文件是 AIMH 所有 `memory/**` 事件包**写入与 lint 校验的唯一权威契约**。
> 所有落库 skill（`aimh-ingest` / `oc-dossier` / `aimh-project` / `aimh-recall` / `aimh-always`）与 `scripts/core/lint_memory.py` 都以本文件为准；**不再于各 skill 内嵌规则副本**（避免漂移）。
> 字段语义 / 哲学推导 / 引擎实现细节见 design-journal 其余文档（见 §6 索引），本文件只写「现在必须怎么写、lint 怎么查」。
> 与 Karpathy LLM Wiki 的 `AGENTS.md` 同构——但 AIMH 把它做成**软契约（本文件）＋ 硬约束（hma_core 引擎）＋ 校验兜底（lint_memory.py）**三层。

## 1. 存储层契约（CEMA）

- 事件包 = 一个 `.md`（`---` YAML front-matter ＋ `##` 标题树正文）＝ **唯一权威源**；`index.db` 是派生薄索引，删了可由全部 `.md` 的 front-matter 全量重建。
- **零依赖 / 零 ML**：`hma_core` 仅用 Python 标准库（`sqlite3/json/re/os/...`），无向量、无嵌入；检索只发生在索引层，命中唯一 ID 后才取正文。
- **命名空间目录硬隔离**：`memory/<agent>/`（项目 / 原创角色 / 用户 / 日志 / 对话 / 其他 / cache 等）各自独立 store。

## 2. Front-matter V2（落库照抄本节 + §2.8 范本）

### 2.0 总原则

- front-matter 以单个 `---` 包裹；**body 为唯一内容源**（anchors 仅关键词/梗概、不内联 body）。
- 空字段**写空容器**（`[]` / `{}`），**不省略整行**、不写 `none` / `null` / `""`（会被当字面值污染数据）。
- 实体 / 属性 / 地点类字段须**锚定正文**（写入时规范化）。
- **四要素是一等字段：包有对应内容就「必须填」，不填 = 漏召回**。
- **变体归一单一出口**：所有「模糊 / 近义 / 别名 / 特征」表述不再有独立字段，统一写成**「规范名作 key、变体列表作 value」的 JSON 对象（字典）**，直接挂在实体字段（person / topic / location）上，走与 anchors 同源的 `json.loads` 解析通道。
  - 例（person）：`{"示例角色": ["示例别名", "示例代号", "自由佣兵", "X-2"], "示例人物·罗曼诺夫": ["黑寡妇", "罗曼诺夫"], "塞莱丝汀·杜·拉克": []}`
  - 例（location）：`{"示例地点": ["苏联", "铸造厂"], "曼哈顿": []}`
  - topic 的 value 数组里，纯年份/日期元素 = 该事件**发生时间**，其余为名称变体。
  - 内层变体用**半角逗号**（JSON 数组天然逗号分隔）。⚠️ `{"示例别名","示例代号",…}` 是 Python 集合写法，JSON 无集合类型——变体列表须用 `[]` 数组。
  - 解析：引擎 `_parse_fm` 对任意以 `[` / `{` 开头的值**先试 `json.loads`、失败回退逗号切分**（与 anchors 同源）。故变体字段须写成合法 JSON 对象/数组。
- **⚠️ FM 内容填写铁律（人工语义逐项填写，禁止机械偷懒）**：`anchors[].keywords` 的 5 维、`person`/`location`/`topic` 四要素变体 dict、以及每章 `about`——**必须由 AI 逐章阅读正文、按语义理解后人工填写**，严禁用机械脚本 / 正则 / 批量 `for` 循环去"按章抓词、填空补齐"。机械补词必然产生两类劣质结果：① 把泛标签、引导语残片、别名/代号塞进 keyword（违反 §2.7 约束）；② 无视真实缺维、只填自以为的某一维糊弄检查。机械解析只可用于**结构归一**（字段形态 / 空容器 / 去旧 schema），绝不可用于**内容语义填充**。内容填完须逐章核对：每 anchor 确实覆盖 5 维、四要素变体确为规范名＋正文真出现的别名/代号/时间。
- **⚠️ FM 写入后必须回读自检（写后关闭纪律）**：**任何 AI 对 FM 的写入（内容填充 / 结构归一 / 字段修订）落盘后，必须回头把改动文件从头到尾通读一遍**，逐项确认：① 11 字段形态正确、无禁写字段（`id`/`created`/`updated`）、无空串 `""`/`none`/`null`；② 四要素变体 dict 为规范名＋正文真出现别名/代号/时间、无臆造；③ 每 anchor 的 5 维 token 均为正文真词、无泛标签 / 引导语残片 / 重复项；④ 正文一字未动。**自检全绿才算写入完成，方可关闭任务**；发现任何遗漏/噪音/误伤必须立即修，不得"写好就交差、撤完不复查"。此纪律专为防住"机械填完即交差、撤完不回读"类失误。
- **字段齐备性（必现 + 空容器）**：V2 规定集（title / summary / tags / linked / anchors / person / event_date / location / topic / pkage_created / pkage_updated）**每包 front-matter 都必须齐备出现**，确定性解析要求解析器始终能定位到键、不因缺键走猜测分支。无内容字段**写空容器而非省略整行**。
- **写入顺序（keyword 先 → 理解归纳 → 四要素描述表达式）**：写入时先提 `keyword`（章节级表面词），再「理解归纳」形成四要素描述表达式（canonical+变体 dict）。`keyword` = 观察（这章实际出现了什么）、四要素 = 理解归一（把表面词归到规范名 + 补别名/代号/时间）；描述表达式由 `keyword` 并集推导 → canonical 名天然对齐、不 desync。⚠️ 「归纳」= `keyword` 并集取 canonical + **AI 补别名/代号/时间**（理解层本职），不可只照搬 `keyword`（否则四要素丢变体 → stage1 别名解析失效）；person 填写规矩(实测词频)仍适用；增删章节须重跑归纳保持同步。`keyword` 是**章级**、四要素是**包级**，归纳时跨章聚合。

### 2.1 序列化格式（inline 单行 JSON 或 block 换行式 均可）

**列表 / 字典字段可写成 inline JSON 单行 或 block 换行式，二者引擎均正确解析**（引擎 `_parse_fm` 已升级为块感知解析器，不再有「block 被静默读丢」的坑）：

- `tags` / `linked` → inline `[ a, b, c ]`（无引号中文项亦兼容，如 `[oc, origin包]`），或 block 每行 `- 项`
- `person` / `location` / `topic` → inline `{"规范名": ["变体"]}`（无内容写 `{}`），或 block `规范名:` 后每行 `- 变体`
- `anchors` → inline `[{"Chapter": "...", "about": "...", "keywords": [...]}]`，或 block 每项 `- Chapter/about/keywords`（keywords 再 block `- 词`）

> 推荐 block 换行式（人读直观、diff 友好）；inline 单行更紧凑。二者都合规。写入侧 `to_markdown` 当前固定产出 inline 单行，故引擎回写后落盘为 inline；手写的 block 文件读取无误。

### 2.2 字段齐备性（11 必填，必须都出现）

`title` / `summary` / `tags` / `linked` / `anchors` / `person` / `event_date` / `location` / `topic` / `pkage_created` / `pkage_updated`

- 无内容的字段写空容器：`[]`（列表）/ `{}`（字典）；`event_date` 无时间信息写哨兵串 `"—"`（仍标量、区别于 `pkage_created` 收录时间，召回不注入时间信号）；**禁止省略整行**，禁止写 `none` / `null` / `""` 字面值（会被当字面值污染数据）。

### 2.3 禁写字段（身份由路径派生 / 折进四要素 / pkage_* 替代）

- 无 `id`（包身份 ＝ 文件路径派生的复合键）
- 无 `aliases` / `features`（别名 / 变体一律折进四要素 dict 的变体数组）
- 无 `created` / `updated`（统一 `pkage_created` / `pkage_updated`）

### 2.4 四要素（一等字段，有内容必填）

`person` / `event_date` / `location` / `topic`：

- `person` / `location` / `topic` ＝ 写时规范形态为 list 包裹 `[{规范名: [变体]}]`（或 block 换行式；无变体写 `[]`；无内容写 `[]`）。读取侧兼容旧式裸 dict 并归一。包内作为内容主语的人物实体（规范全名），出现多次即加入；AI 不凭记忆、须实测词频；base 包只放 OC 自己名。
- `event_date` ＝ 标量字符串，按内容性质分两种形态，**由内容决定取哪种、不混用**：
  - **(A) 事件发生时间（单点）**：`YYYY-MM-DD`（粒度到日），如某次会议 `2026-03-15`。
  - **(B) 长线故事时间跨度（区间）**：`YYYY-YYYY`（起-止年），如 demo-origin `1969-2012`。
  - **(C) 无时间信息（哨兵串）**：写 `"—"`（仍标量，明确区别于 `pkage_created` 收录时间，召回不注入时间信号）；不写 `""` / `[]`。
- **实体名不进 `tags`**，收进四要素变体 dict（tags 只放分类标签，不与四要素重复）。

### 2.5 包生命周期时间戳

- `pkage_created`：收录时间；重填时保留原值，不刷成今天
- `pkage_updated`：每次文件更新后刷新日期

### 2.6 linked（复合 id）

关联包相对 `memory/` 根的复合 id（含目录 ＋ `.md`），如 `原创角色/示例角色/demo-base.md`；不用裸文件名。
⚠️ 复合键带归属，跨项目同名 `.md` 不再歧义；`read()` 按复合 id 查 filepath，关联更稳。
⚠️ **人物 / 实体文件夹须用全名**（如 `示例角色` 而非 `demo-char`）：复合键含完整目录路径，片段名会削弱无歧义归属。（用户原话「人物也得是全名」指**文件夹名称**，非 person 字段。）

### 2.7 anchors（唯一形态）

`[{Chapter, about, keywords}]`（inline JSON 数组，或 block 换行式：每项 `- Chapter/about/keywords`）：

- `Chapter` ＝ 稳定小节标题 / 定位键（无需独立 `locator` 字段）
- `about` ＝ 该节概述短答（自然语言一句，可直答"这章讲什么"类问题；同时参与锚点匹配与二次消歧）。**⚠️ about 必须特征化、严禁泛化锚点（铁律·2026-08-24 立，不可妥协）**：about 必须写成该章独有的、可判别的特征化摘要——只承载本章专有名词、具体论断、唯一性事实；**绝不允许写可被同包其他锚点共现的泛化套话**（如"本文延伸""方法思路概述""相关讨论""总体说明"等无信息量空壳句）。判定红线：**若把某锚点的 about 抽掉章名后仍能与同包其他锚点的 about 互换而不违和，即为泛化锚点，违规**。违规后果（已实证）：同包多锚点 about 互含高频泛词 → BM25 排序彼此稀释 → 目标锚点被邻近锚点挤出 top5（regress_paper_camus P08 红基线：review 包「方法思路」锚点被 `III.加缪的位置与本文的延伸` 泛化 about 压到 top5 外，即此）。AI 填 FM 须逐章读正文语义、写死每章独有特征，严禁模板/循环/批量补泛词（见 §2.0 人工填写铁律）。
- `keywords` ＝ 章级定位词数组（扁平即可），**须满足「5 维完整性契约」（2026-08-13 立·必写）：每锚点 keywords 至少覆盖 时间 / 地点 / 关键事件 / 锚定物品 / 人物 各 ≥1 token**；抽象章（无实体物件，如「处决良知」）以该章最具辨识度概念词顶替锚定物品维（如 `良知`/`生活`/`逃亡种子`）。引擎做扁平 token BM25 匹配；这是**必写字段**，缺维＝漏召回（非可选、非"写时建议"）。
  - **时间**：章级时点/年份（如 `2005`/`1994`）——包级 `event_date` 只存跨度，章级时点留 keyword 作检索信号；
  - **地点**：章级空间（如 `圣保罗`/`布达佩斯`/`铸造厂`）——与四要素 `location` 互补（四要素是包级、keyword 是章级）；
  - **关键事件**：章核心动作/事件名（如 `示例信物`/`示例事件`/`示例协议`）——非四要素实体真名也放这（如 `示例信物`/`布达佩斯`/`安全屋`）；
  - **锚定物品**：章核心物件 / 语义属性（如 `宝石`/`钻石`/`珠宝`/`示例设定`/`完美超级士兵血清`）——专收「这章*涉及什么物*」的词（宝石是示例信物的属性描述，非其别名，故不进四要素变体、只进此维）；抽象章（无实体物件，如「处决良知」）以该章最具辨识度概念词顶替（如 `良知`/`生活`/`逃亡种子`）；
  - **人物**：章主语规范名（如 `示例角色`/`示例人物·罗曼诺夫`）——代号（`示例代号`/`黑寡妇`）不进 keyword、收四要素变体。
  - 约束：keyword 只放该章「真出现、有辨识度」的词；**不放泛标签、不放别名/代号**（别名/代号归四要素变体 dict，由 `query()` 解析为 canonical 后透传，单点维护）。
- **锚点匹配（扁平 BM25，无选章子系统）**：`query_anchors()` 对 `{Chapter, about, keywords}` 做扁平 BM25 匹配，返回锚点候选（含 `about` 短答与正文定位键）。包级召回由 `query()` 用四要素变体 dict 锁定到包，锚点匹配只在包内选章，不重复做包级召回。别名/代号经四要素变体 dict 在 `query()` 阶段解析为 canonical 后透传，保证锚点精确命中。检索细则见 `AIMH核心规格（极简·当前实现）.md` §2–§3。
- **无 `locator` / 无 `tags`**（出现即为旧 schema 残留）

### 2.8 标准范本（ block，照抄）

```yaml
---
title: 包的人类可读标题
summary: 2~4 句自包含真概要（概括本包现在是什么，不写"已废弃/已移除"等元备注）
tags: [recall, 歧义门, 设计]
linked: [项目/AIMH-design-journal/存储架构总览.md]
person: [{"示例角色": ["示例别名", "示例代号"]}, {"示例人物·罗曼诺夫": ["黑寡妇"]}]
event_date: YYYY-MM-DD/YYYY-YYYY
location: [{"示例地点": ["苏联", "铸造厂"]}]
topic: [{"回旋镖计划": []}, {"示例协议": ["2008", "协议X"]}, {"示例信物": ["黄/橙", "蓝", "双色", "宝石", "价值连城"]}]
anchors:
  - Chapter: "1. 章节标题"
    about: "该节概述短答（自然语言一句，可直答这章讲什么）"
    keywords: ["2005", "曼哈顿", "示例信物", "宝石", "示例角色"]
pkage_created: 2026-08-14
pkage_updated: 2026-09-02
---

# <标题>

<markdown 正文，原样收录，不压缩>

## <子事件 / 锚点 1 标题>
<锚点 1 正文：一段凝聚性内容>

## <子事件 / 锚点 2 标题>
<锚点 2 正文>
```

**照抄前逐项核对**：无 `id`/`aliases`/`features`；无 `created`/`updated`；`linked` 复合 id；`anchors` 仅 `{Chapter,about,keywords}`；`anchors[].keywords` **必写覆盖 5 维（时间/地点/关键事件/锚定物品/人物 各≥1 token，缺维＝漏召回）；引擎只做扁平 BM25**；所有列表/字典字段 inline 单行 或 block 换行式；空字段写 `[]`/`{}`/`""`。

### 2.9 对话记录 tags 派生与矛盾处理

- tags 由 `## 关键内容` 每条决定抽「决策主语 / 规范实体」得来（单一真相源，不手工另写）。
- 矛盾 / 反向更新：引擎只忠实保留相左事实都检索得出，由 AI 理解层判定用哪条，写入时绝不静默覆盖旧决定。

## 3. 锚点模型与检索契约（含四要素适配器）

- **锚点三字段**：`Chapter` 兼正文定位键；`about` 概述短答（可直答概述类问题，但**必须特征化、严禁泛化**——见 §2.7 `about` 铁律，泛化 about 致同包 BM25 稀释挤掉目标锚点）；`keywords` 章级定位词（**必写覆盖五维：时间/地点/关键事件/锚定物品/人物，缺维＝漏召回**，由 `hma/fm_schema.py` 的 `check_kw5` 写前硬过滤 + `lint_memory.py` 兜底校验）。详见 `AIMH核心规格（极简·当前实现）.md` §3。
- **三层检索**：`query()`（包级 BM25）→ `query_anchors()`（锚点级 BM25）→ `read_section()`（取正文段）。概述类问题优先读 `summary` / `about`；包/实体级歧义由 `resolve_query`（歧义门 + 特征判别澄清 + 负特征差集，确定性、零 LLM）处理。
- **字段权重**（读时软加权，永不剔除候选）：`person4 > time3 > loc2 > topic1`。
- **裁切与 rerank**：`waterfall_cut`（锚点级 dK 分差 >75 单向裁切）收束候选；包级 BM25 rerank 装置保留但默认关（`rerank=False`），重开前必须先改成锚点级。「自以为是层」（rule#1 / OR-fail-safe 保 gold 逻辑）已全删，绝不重写回 core。REFINE 的**语义桥接**（LLM/词典形态）与 embedding 后备**未接入引擎**——语义桥接归AI 理解层，引擎侧仅保留 refine 的机械兜底拒答闸 `corpus_overlap_absent`（零 ML、零向量），不依赖。
- 检索接口细则见 `AIMH核心规格（极简·当前实现）.md`；实体歧义门设计见 `召回消歧管线设计（实现）.md` / `召回消歧的数学与语言哲学思路.md`；存储/命名空间见 `存储架构总览.md`。

### 3.1 四要素适配器（写时映射 / 读时加权 / 跨包查询）

> 四要素的**字段定义**（类型 / 语义 / 存储格式）见 §2.4；本段只讲**适配器机制**。

- **核心原则**：① 核心引擎最小、内容无关——`hma_core.Memory` 只认规范 schema，不内置领域语义；四要素是 `events` 表上的可选列，由适配器填充。② 适配器只负责**写时映射**，不定义字段——把领域原始数据翻译成四要素取值，自由度在映射逻辑。③ 读时加权**通用、不门控**——写一次、对所有声明了字段的包统一生效，**永不剔除候选**（保召回、降干扰）。④ **跨包查询是默认能力**——四要素查询对 `package_id` 无关，同一 `index.db` 内不同适配器的包可用一条 SQL 联合捞出。
- **适配器契约（写时映射）**：适配器 = 把某领域原始数据 → 规范 schema + 四要素取值 的确定性函数。已落地实例：
  | 适配器 | 数据源 | `person` | `event_date` | `location` | `topic` | `tags` |
  |---|---|---|---|---|---|---|
  | **LCM 对话适配器**（`locomo_ingest.py`） | LoCoMo `locomo10.json` | 对话说话人集合 | 解析出的会话 ISO 日期 | `[]`（对话地点弱） | `[]`（主题另行抽） | `["locomo", conv_id]` |
  | **OC 叙事适配器**（待建） | Demo/OC 文本 | 出场角色 | 章节/时间线日期 | 场景地点 | 章节主题 | `["oc", ...]` |
  | **笔记适配器**（待建） | 用户笔记 | 涉及者（如有） | — | — | 笔记主题关键词 | 主题标签 |
  约束：适配器**不得**把人物塞进 `tags`、不得把事件日期塞进 `created`。字段族为「可选」：某领域缺某维度就留 `[]`，加权逻辑对空维度自然降级，不报错。
- **读时通用加权接口**（零 API）：已落地为引擎原生能力 `Memory.query_anchors(q, ..., use_field_weights=True)`，在 BM25/rerank 之后叠加四要素软加权，永不剔除候选。主排序 = 命中要素数（降序）；次 = 加权 bonus（`W_P=4, W_T=3, W_TOP=1, W_L=2`）；tiebreak = 原 BM25 分。实测（1540 题，引擎原生）：BARE 基线加权后 recall@1 **43.62%→62.89%(+19.27)** / @5 **77.73%→83.46%(+5.73)**（只调序，弱检索器上的有效补丁）；FULL 基线加权 ≈0（已隐式编码要素相关性，互为替代非互补）。
- **跨包查询契约**：字段族查询对 `package_id` 无关。验证：同一 `index.db` 内写入第二个包 `oc_demo`（填 `person/location/topic`），一条 `SELECT package_id, id FROM events WHERE lower(person) LIKE '%melanie%'` 返回跨 `{'locomo':19, 'oc_demo':2}` 的 21 行——证明「Melanie 在对话和 OC 里」可用一条 SQL 联合捞出。这是把 HMA 从「单基准优化」升级为「可扩展领域记忆架构」的关键能力。

## 4. 命名空间与拆包契约

| 命名空间 | 落点 | 特殊约定 |
|---|---|---|
| daylog | `memory/日志/` | 一天一包，日期即主键；检索层不存正文（blob=FM 层文本，正文按需打捞）；anchors 每 beat 一锚点，keywords 数量从简但不为空（daylog 口径豁免通用 5 维），规矩见 daylog设计.md |
| project | `memory/项目/` | README 式功能拆包（需求清单 / 项目结构 / 开发日志 / 约定 各成 md） |
| OC | `memory/原创角色/` | base（必有仅 1）／ origin（默认必有）／ ext（有则分） |
| 对话 | `memory/对话/` | `summary`=背景；`##对话原文`＋`##关键内容`；`tags` 由关键内容派生 |
| user | `memory/用户/` | 主语＝用户本人；默认 5 模块（偏好 / 方法论 / 身份锚点 / 踩坑 / 事实） |
| 其他 | `memory/其他/` ＋ `memory/cache/` | 文章 orig＋review 互链；cache 溢出兜底 |

- 细则见 `存储架构总览.md`。

### 4.1 用户数据模块划分（user）

落点 `memory/用户/<模块>/`，主语必须是**用户本人**（不进话题类目）。默认五个凝聚模块（偏好 / 方法论 / 身份锚点 / 踩坑 / 事实）及其「装什么 / 不装什么」表，详见 `存储架构总览.md` §5 user。本段只管「往哪个模块落」的路由判定，存储细节去总览。

> 模块是**默认路由指南**，不是强制分类法。AI 收录时先判内容命中哪个模块，再落点；小内容可先作为同包内的不同事件 id，不必硬拆成独立包（见 §4.3 拆包触发铁律）。

### 4.2 项目工程模块划分（README 式功能拆包）

落点 `memory/项目/<项目名>/`，**仿照一个普通项目的 README 做功能拆包**，而非按技术子系统切（读者视角：需求 / 结构 / 日志 / 约定，非实现视角）。各模块职责（需求清单 / 项目结构 / 开发日志 / 约定 各成单独 `.md`、每 md 单一职责、铁律进约定不混）详见 `存储架构总览.md` §2 project。

### 4.3 拆包触发铁律：凝聚性 + 体积

对应设计原则③「活文档整合 / 无限拆分」——**拆包触发条件是体积 / 凝聚性，不是作者写法运气**。

- **不提前拆小东西**（CEMA 原设计）：小内容硬拆成独立包 = 索引碎片化、检索噪音、维护成本上升。
- 本策略的「模块分类」定位是：帮 AI 快速落点的默认路由指南，而非「必须先建好所有空模块」。
- 过度拆分的信号：一个包只有一两句、或模块间高频互链成网状——此时应合并或升级为更高阶包。

### 4.4 AI 收录时的模块路由判定

落点决策（配合 `aimh-ingest` 步骤 2 的「一次比对 index」）：

1. **判命名空间**：用户 / 项目 / 其他 / OC / 日志 / 对话。
2. **判模块**：内容语义命中哪个默认模块？（用户→五模块；项目→README 式功能模块：需求清单/项目结构/开发日志/约定）
3. **比对 index**：该模块包是否已存在？
   - **存在且同物** → **增补 / 覆盖该包**（update 同包，不新建）。
   - **存在但过大**（体积触发） → 在该模块下拆子包 / 子事件 id。
   - **不存在** → 仅当凝聚性确实成立，按「嵌套逻辑关系」新建模块包。
4. **严禁**：把不同模块内容塞进一个包；为小内容预建一堆空模块包。

> 此规则已写入 `aimh-ingest` 技能「模块路由」段，AI 收录时实际执行。

## 5. lint 契约（`scripts/core/lint_memory.py` 检查清单）

脚本确定性扫描所有 `memory/**/*.md` 的 front-matter，报 **ERROR**（非零退出码）的项：

1. 缺 11 必填字段之一（顶层 key 未出现）
2. 出现禁写字段 `id` / `aliases` / `features` / `created` / `updated`（顶层）
3. 列表 / 字典字段写法非法（裸标量脏写法：既非 `[`/`{` 单行 JSON，也非 block 换行式；如 `tags: recall` 无括号）
4. `anchors` 含旧 `locator:` / `tags:` 子键
5. 经引擎 `from_markdown` 解析后 `person`/`location`/`topic` 非 dict，`tags`/`linked` 非 list（即未被引擎正确解析）

报 **ERROR** 的项（续上，写前门禁 `check_kw5` 同口径）：

6. 锚点 `keywords` 经 `check_kw5` 校验缺 5 维（时间/地点/关键事件/锚定物品/人物）任一时 → ERROR（必写契约，缺维＝漏召回）

报 **WARN** 的项：

- 无 front-matter 块的 `.md`（非事件包文档）
- design-journal 规格文档自身 anchors 已统一为 `Chapter`/`about`/`keywords` 规范形态（与全库一致），无需单列 WARN

## 6. 细则索引（推导 / 哲学 / 实现，非落库契约）

- `存储架构总览.md` —— 各命名空间存储契约细则（用户五模块表 / 项目 README 拆包职责 / 隔离拓扑）
- `AIMH核心规格（极简·当前实现）.md` —— 检索接口与"不做"边界（当前实现唯一真相源）
- `召回消歧管线设计（实现）.md` / `召回消歧的数学与语言哲学思路.md` —— 实体歧义门（`resolve_query`）实现与推导
- `什么是AIMH系统.md` / `工具与技能总览.md` —— 系统总览

> ⚠️ 注：`skills/aimh-ingest/references/packs_template.md` 提供 inline 范本。`lint_memory.py --all` 现已零 ERROR；design-journal 各规格文档的 anchors 已统一为 `Chapter`/`about`/`keywords` 规范形态——与全库一致，引擎按正文 `derive_anchors` 重派亦产出同形态，无需手动迁移。
