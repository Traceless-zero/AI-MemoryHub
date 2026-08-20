---
name: aimh-ingest
description: >
  把一段通用文本 / 笔记 / 日志 / 文章 / 资料 / 想法存入 HMA（Hybrid Memory Architecture）
  长期记忆时，本技能定义「Agent 即理解层」的零成本收录流程，含三个分支（通用 / 文章·资料 / 对话记录）：
  （A）通用分支——零散文本 / 笔记 / 想法 / 用户自身数据 / 项目工程，拆成 1+ CEMA 凝聚性包；
  （B）文章·资料分支（原 paper-archive）——论文 / 长文 / 资料要"归档 + 理解综述"时，
  强制产出「原文包 + 理解综述包」一对；
  （C）对话记录分支——会议 / 访谈 / 对话流，产「谈话背景 + 逐字对话原文 + 拍板关键内容」单包。
  何时用（命中即加载）：

  - 关键词：记一下、存进记忆、收录这段、存个笔记、记住这个、写进记忆、HMA、长期记忆、ingest、note、整理成记忆、论文、文章、文献、综述、归档这篇、读懂这篇、对话、会议、访谈、对话记录、把这场会存一下
  - 口语化：「帮我把这段存进记忆」「这段话记一下」「把这篇笔记收进 HMA」「把我的想法存下来」「把这篇论文收进记忆并写个理解」
  - 凡用户给一段非角色类文本、要求存入 HMA 记忆库时，先加载本技能

  注意：若文本明显是「一个角色 / OC 档案」（用户说"存个角色"或含 姓名+形象+背景 结构），
  本技能会把你导向 oc-dossier（store 分支），不在本技能里手拆 OC。
---

# HMA Ingest（Agent 即理解层，零成本）

## Overview
把**通用文本 / 笔记 / 文章 / 资料**录入 HMA 长期记忆。HMA 的落库是「确定性 + 可重建索引」的：本技能让**当前会话的 Agent（你）充当理解层**——你负责把文本拆成 CEMA 凝聚性事件包、生成元数据、发现关联；引擎（直接写 `memory/`：`python -m hma.cli --root memory/<scope> write ...` 或 `Memory(root).write(...)`）负责确定性落库与索引。**无需任何 API key，零成本**。

本技能含三个分支：**通用分支**（下方「通用收录流程」，零散文本 / 笔记 / 想法 / 用户自身数据 / 项目工程）、**文章·资料分支**（论文 / 长文归档 + 理解综述，见「文章·资料分支」一节；原 `paper-archive` 技能已并入此分支），与**对话记录分支**（会议 / 访谈 / 对话流，见「对话记录分支」一节；产「谈话背景 + 逐字对话原文 + 拍板关键内容」单包）。

> **同构可替换后端**：当用户日后配置了真实 LLM（设了 `OPENAI_API_KEY` + `HMA_LLM=openai` 等），`note` 模式会自动改用 `hma/llm_adapter.py` 的付费/本地路径，产出与本技能**完全相同**的包结构（都遵循下文的 `ingest_prompt` 规则）。本技能就是那个「没有 key 也能跑」的客户端；两条路共用同一套引擎落库，互不冲突。

## 如何调用（接口）
- **技能名（入口）**：`aimh-ingest`。收到"把这段存进记忆 / 记一下 / 收录"类请求，且内容**非角色**时，第一步加载本技能。
- **内容若是角色 / OC**：改加载 `oc-dossier`（store 分支，它会按 OC 三层铁律落库，见下方"路由"）。
- **内容若是论文 / 长文资料且要"归档 + 理解"**：走下方「文章·资料分支」，产出原文包 + 理解综述包。

## 路由（先判断，再动手）
- 文本明显是"一个角色 / OC 档案"（用户说"存个角色"，或含 姓名 + 形象 + 行事调性 + 背景）：**加载 `oc-dossier`（store 分支）**，交给 OC 流程，不要在本技能里手拆 OC。
- 文本是论文 / 文章 / 长文资料，且用户意图含"归档 + 理解 / 综述 / 读懂"：走下方「文章·资料分支」。
- 文本是**会议 / 访谈 / 对话流**（用户说"把这场对话存一下""记一下刚才的会"，或给逐字 transcript / 对话稿）：走下方「对话记录分支」。
- 否则走下方"通用收录流程"。

## 模块路由（用户/项目 按模块增补，不混不散）
收录**用户自身数据 / 项目工程数据**时，按模块落点、对已有模块包做"增补/覆盖"而非新建单体。这是 HMA「活文档整合 / 无限拆分」原则（拆分由凝聚性+体积触发）的落地。详见设计包 `SCHEMA.md` §4。

**用户数据默认模块**（落 `memory/用户/<模块>/`，q-2 铁律：主语是用户本人）：
- `偏好`：稳定偏好 / 习惯 / 工具风格选择
- `方法论`：可复用的工作/思考方法、"以后这么做"
- `身份锚点`：自我描述 / 角色定位 / 长期身份事实
- `踩坑`：具体教训、易错点（"别踩"，与方法论互补）
- `事实`：与项目无关的稳定个人事实（家住 X、用 X 设备）

**项目工程默认模块**（落 `memory/项目/<项目名>/`，README 式功能拆包，一个 md 一类职责）：
- `需求清单`：要做什么，显式标 `已完成` / `未完成`（活待办 / roadmap）
- `项目结构`：**只描述目录布局，严禁塞铁律 / 约定 / 架构决策等"死东西"**
- `开发日志`：结构化、按时间的工程记录（决策 / 改动 / 踩坑经过）
- `约定`：铁律 / 协作约定单独成文件，与结构、日志解耦
- 其余按需（`架构` / `接口` / `测试` 等），每 md 单一职责；某块涨到该拆再拆，**不提前建空包**

**日志/（daylog）仅装闲话 + 大事件简介 + 关联**：结构化项目跟踪（需求状态、决策记录）进 `项目/<项目>/` 对应包，**不进 daylog**；daylog 靠 `linked` 把碎片挂到正经包上，自己不承载真相。

**落点决策**（配合步骤 2 一次比对 index）：
- 内容命中某模块语义域 → **增补进该模块包**（update 同包，不新建），除非该包已过大（体积触发）→ 在该模块下拆子包/子事件 id。
- 跨模块的新主题 → 按「嵌套逻辑关系」新建模块包。
- **绝不**：把不同模块内容塞进一个包；为小内容强行预建一堆空模块包。

## Front-matter 落库契约（唯一真相源：SCHEMA.md）

> ⚠️ **列表/字典字段可 inline JSON 单行 或 block 换行式**（tags/linked 用 `[..]` 或每行 `- 项`；person/location/topic 用 `{}`/`[..]` 或 block；anchors 同理）。引擎 `_parse_fm` 已支持 block，二者都正确解析，不再静默读丢。
> 完整权威契约见 `memory/项目/AIMH-design-journal/SCHEMA.md` §2（落库与 `scripts/core/lint_memory.py` 校验的唯一真相源）。本技能**不再内嵌规则副本**，避免漂移。
> 任何落库（通用 / 文章·资料 / 对话记录 / OC）都须遵守；禁写 `id` / `aliases` / `features` / `created` / `updated`。

### 照抄范本（inline 单行，引擎可正确解析）
完整可抄范本：`skills/aimh-ingest/references/packs_template.md`（inline 版）或 SCHEMA.md §2.8。要点速记：
- **11 必填字段齐备**：title/summary/tags/linked/anchors/person/event_date/location/topic/pkage_created/pkage_updated；无内容写 `[]`/`{}`，`event_date` 无时间信息写哨兵串 `"—"`（仍标量、区别于 `pkage_created`、不用 `""`）；不省略整行、禁 `none`/`null`/`""` 字面值。
- **禁写**：`id`（路径派生）/ `aliases`/`features`（折进四要素 dict）/ `created`/`updated`（改 `pkage_*`）。
- **anchors** 唯一形态 `[{Chapter, about, keywords}]`，无 `locator`/`tags`；`keywords` 满足 5 维（时间/地点/关键事件/锚定物品/人物 各 ≥1 token）。
- **inline 单行 JSON 与 block 换行式均可落库**：引擎现已正确解析 block（不再静默读丢）。推荐 block（人读直观、diff 友好），inline 更紧凑，任选其一。

### 落库方式（CLI 旗标无法携带四要素，推荐直写 .md）
- **推荐：直写 `.md`**——按上方范本写好 `memory/<scope>/<id>.md`，再 `python scripts/core/rebuild_index.py --no-gui` 重建索引（或 `Memory(root).rebuild_all()`）。
- **或 Python `Memory(root).write(...)`**——传 `person`/`location`/`topic` 为 dict、`event_date` 为字符串、`anchors=[{Chapter,about,keywords}]`；`pkage_created`/`pkage_updated` 经 `created`/`updated` 入参落盘；不要传 `aliases`/`features`（V2 已折进四要素）。
- 旧 CLI `write --id --title --summary --tags --aliases --linked` 旗标**会丢四要素 / pkage_ 时间戳**，仅适合极简包；正式落库请用直写 .md。

## 通用收录流程
1. **定位 root（落库目录）**：按内容选一个 scope 目录，例如：
   - 通用笔记 / 想法 → `memory/notes`
   - 项目相关 → `memory/<project>`
   - 外部主题 / 资料 / 论文 → `memory/其他/<主题>/`（见下方「嵌套逻辑关系」）
   - 用户自身数据 → 按「模块路由」落 `memory/用户/<模块>/`（默认模块：偏好 / 方法论 / 身份锚点 / 踩坑 / 事实；**q-2 铁律**：主语是用户本人的才进 User，不进话题类目）
   - 用户指定了 scope 标签则优先用

   **嵌套逻辑关系（通用纪律，来源 aimh-intake）**：新建文件夹路径须**按内容的逻辑从属
   嵌套生成，不要摊平**。例：用户给一篇「尼采综述」→ 路径应是 `memory/其他/哲学/尼采/`，
   其下两包 `<尼采原文.md>`（原文）+ `<尼采综述与理解.md>`（AI 理解综述），二者互链；
   同理 `memory/其他/科学/数学/`。OC 角色同理 `原创角色/<角色>/`（下分 core/origin/ext）。
   引擎 `query(package_id=...)` 已支持**前缀/子孙检索**（scope="哲学" 命中 "哲学/尼采" 子树，
   scope="哲学/尼采" 精确到该节点），故嵌套**不破坏检索**，放心嵌套。仅当内容确为单级、
   或用户明确要求摊平时才用单级 `Other/<主题>/`。
2. **一次比对 index（同时完成「归并候选」+「关联发现」）**：在 `hma/` 目录下跑
   ```bash
   python -m hma.engine query <root> "<关键词/标签>"
   ```
   只取 id / title / summary（不扫正文）。从返回里**一次**分出两类：
   - **归并候选（merge_candidate）**：某已有**包**的主题与本次内容高度同构、疑似"同一事物"。
   - **关联事件（linked）**：相关但非同物（背景 / 延伸 / 对照）。
   这一步把"查比对（防碎片）"和"查关联（防孤立）"合并成一次 query，不分开跑。两者皆空则正常新建、不强关联。
3. **你（Agent）理解并拆分 + 决定落点**：严格遵循 `references/ingest_prompt.txt` 的规则，把文本拆成 1+ 个 CEMA 凝聚性事件包。落点判定：
   - 若步骤 2 有 `merge_candidate` 且你判断确为同一事物 → **归并**：直接写进该已有包（不新建）。
   - 否则 → 按上方「嵌套逻辑关系」新建包。
   每个包产出（front-matter 字段严格按上方「Front-matter 落库契约」与 SCHEMA.md §2 范本）：
   - `id`：仅作 `.md` 文件名 slug（kebab-case 且全局唯一，小写、保留中文与字母数字、其余折叠为 `-`），**不是 front-matter 字段**。建议 `<scope>-<短主题>`。
   - `title` / `summary`（2~4 句自包含真概要）/ `tags`（2–5 个）/ `linked`（复合 id）/ `anchors`（{Chapter,about,keywords}）/ 四要素 `person`/`topic`/`location`（写时规范形态为 list 包裹 [{规范名:[变体]}]，读取侧兼容旧式裸 dict）/ `event_date` / `pkage_created` / `pkage_updated`
   - `body`：markdown 正文（`# 标题` 开头）
   - 跨包关联：仅当某包与步骤 2 发现的 `linked` 关联事件或**本次同批新建包**真正相关时，记下链接（复合 id）。
   **严禁**：把多个无关主题塞进一个包；编造不存在的现有 id 做关联；写 `id`/`aliases`/`features`/`created`/`updated` 等已废除字段。
4. **落库（确定性 sink = 直写 `memory/`）**：把第 3 步拆好的每个包，**按上方「Front-matter 落库契约」与 SCHEMA.md §2 范本写好 `.md` 直接落 `memory/<scope>/<id>.md`**（单一权威存储），再 `python scripts/core/rebuild_index.py --no-gui` 重建索引。
   - 直写 `.md` 是推荐路径：CLI `write` 旗标无法携带四要素 dict / pkage_ 时间戳，会丢字段（见上方「落库方式」）。
   - 等价地可在脚本里 `Memory(root).write(id=..., title=..., summary=..., tags=[...], linked=[...], person={...}, location={...}, topic={...}, event_date="...", anchors=[{Chapter,about,keywords}], created="<pkage_created>", updated="<pkage_updated>")`；`aliases`/`features` 不要传（V2 已折进四要素）。
   - 正文 `# 标题` 开头；引擎从 `##` 派生锚点，但 V2 要求你**显式写 anchors**（5 维关键词），不要留空让引擎盲派。
5. **记当日账（daylog，叙事型，收录即写）**：落库成功后，给当天的单日记录包**追加一段叙事**（时间轴索引层，支持"我那天都干了些什么"式唤起）。写一句**日记式**的话，描述这天发生的一件事 / 一个进展；可用「先是 / 随后 / 最后 / 接着」等连接词让一天连贯——**不要**写成关键词卡片或"标题 + 摘要"。
   ```bash
   cd scripts/core && python daylog_append.py --title "<一句话小标题>" --linked "<本次落库的包id,逗号分隔>" --tags "<2-4个关键词>" --body "<一段叙事：这天发生的一件事/进展>"
   ```
   - 单日包 id 为 `daylog-YYYY-MM-DD`，默认落 `memory/日志`。一次收录 = 一段叙事；勿把多次收录合并成一段。
   - `--linked` / `--tags` 只是**索引侧车**（类比 WB 自带 memory 的「叙事块 + 结构化字段」）：机器靠它做精准搜寻，不影响叙事可读性。叙事里已讲清的事，不必在 tag 里重复。
6. **主动输出「收录钩子」（流程结束后、非阻塞）**：落库 + 日志完成后，固定输出一段回复钩子，让用户随时可纠错：
   > **📥 已收录至 `<package_id>`**（新建 / 归并进 `<已有包>`）。
   > · 相似已有包：`<merge_candidate 或 "无">` —— 若本就该合并，回复 **「合并 <已有包>」** 触发移包技能。
   > · 关联：`<linked 列表 或 "无">`。
   > · 如需改归到其他路径，回复 **「移包 <目标路径>」** 触发移包技能。
   钩子是"告知 + 可触发"，不阻塞、不追问；用户不回应 = 默认接受当前落点。

## 文章·资料分支（论文 / 长文资料：归档 + 理解综述）

> 原 `paper-archive` 技能已并入本分支。适用：用户给论文 / 文章 / 文献 / 长文资料，意图含"归档 + 理解 / 综述 / 读懂"。
> 核心交付物是「`<主题>-orig` 原文包 + `<主题>-review` 理解综述包」一对，同 scope 互链。
> 若无"读懂 / 综述"意图（只是零散笔记 / 短文本）→ 走上方通用收录流程。

### 流程
1. **判定与取文**：确认是论文/资料类。文件（文本 / PDF 导出的 md / 用户贴文）由你读取；记录元信息（标题 / 作者 / 出处 / 年份 / DOI）。
   · 用户只给"主题"没给原文：先问清源文本在哪（综述不能凭空编原文）。
   · **源是 PDF → 必走确定性重排管线**（`get_text` 裸提取会让双栏顺序乱、零锚点）：
     ```bash
     python scripts/core/pdf_reflow.py <pdf> --out /tmp/<主题>-orig.md   # 试跑抽查
     python scripts/core/pdf_reflow.py <pdf> --write memory <包相对路径> <主题>-orig  # 直接落库
     ```
     管线（全确定性）：按坐标恢复视觉顺序、剥页码/页眉页脚、标标题、拼段落，最后**原样校验**（非空白字符 Counter：raw == body + removed，差一字即 abort）。
2. **定位嵌套路径（按逻辑关系）**：落到 `其他/<学科>/<主题>/`（对齐 aimh-intake「嵌套逻辑关系」）。
   · 例：尼采 → `memory/其他/哲学/尼采/`；某 ML 论文 → `memory/其他/科学/计算机/机器学习/`。
   · 主题不明 → 按你的最佳推断建路径，并走下方「归类开口」。
   · 引擎已支持前缀/子孙检索，嵌套不破坏检索，放心嵌套。
3. **拆成 2 个事件包（同 scope，互链）**：
   - **`<主题>-orig`（原文包）**：`body` 原文正文（纯文本且允许入库时）；大文件 / 敏感 / 版权内容留在仓库外，包内只记一句指向（守「隐私」纪律），如「详见 ~/private/<主题>.pdf」。元信息写进 body 顶部或 `summary`（标题 / 作者 / 出处 / 年份 / DOI）。`summary` 落到关键事实首行，保证 L1 可召回。
   - **`<主题>-review`（理解综述包）**：**核心交付物**，由你（Agent）中文、结构化生成：一句话核心贡献 / 方法思路 / 关键结论 / 与你已有记忆的关联（真相关才 `linked`，不编 id）/ 局限 / 可复用点。`summary` 落核心贡献一句话。
4. **落库（确定性 sink = 直写 `memory/`）**：两包都写进 `其他/<学科>/<主题>/`。
   ```bash
   cd hma && python -m hma.cli --root memory/其他/<学科>/<主题> write \
       --id <主题>-orig --title "<标题>" --summary "<关键事实首行（含原标题/作者/出处/年份/DOI）>" \
       --tags "paper,<学科>,<主题>" --body-file /tmp/<主题>-orig.md
   cd hma && python -m hma.cli --root memory/其他/<学科>/<主题> write \
       --id <主题>-review --title "<主题> 理解综述" --summary "<核心贡献一句话>" \
       --tags "review,paper,<学科>,<主题>" --body-file /tmp/<主题>-review.md
   ```
   > ⚠️ V2 已废除 `aliases` 字段：原标题 / 原标题变体请进 `summary` 或 `topic` 变体 dict，不要写 `--aliases`。CLI `write` 旗标无法携带四要素 dict / pkage_ 时间戳；若论文包需四要素（作者作 `person`、年份作 `event_date`），按通用流程「直写 .md」落库更完整。
5. **互链**：两包互链（`python -m hma.engine ... link <主题>-orig <主题>-review`，或 `Memory.link`），导航上"原文 ↔ 综述"一体。
6. **记当日账（daylog，叙事型，收录即写）**：落库后给当天单日记录包追加一段叙事。
   ```bash
   cd scripts/core && python daylog_append.py --title "<一句话小标题>" --linked "<主题>-orig,<主题>-review" --tags "<2-4个关键词>" --body "<一段叙事：这天归档了某论文并出了理解综述>" \
       --linked "<主题>-orig,<主题>-review" --tags "<2-4个关键词>"
   ```
7. **回报（含「归类开口」，强制）**：列出两包 id / 路径 / 关联；原文过大/敏感留在仓库外则明确说明。凡 `其他/<学科>/<主题>/` 是你推断的（非用户明示），必须带固定句式：
   > **当前归类为 `<路径A>`，如有异议可以切换为 `<路径B>`（次优候选 + 一句话理由）。**
   用户答"换"即跑确定性切换（整目录搬迁 + 索引重挂，linked 按 id 不受影响）：
   ```bash
   python scripts/core/relocate_package.py memory "<路径A>" "<路径B>"
   ```
   用户不回应 = 默认接受，不追问。

### 文章·资料分支纪律（铁律）
- **原文包 ≠ 综述包**：二者必须分开（空间换复杂性）；综述是附加值，不回写覆盖原文。
- **嵌套优先**：路径按学科→主题嵌套，不摊平（子孙检索已支撑）。
- **论文体锚点规则（最小单元）**：论文每节关键且独立，故 orig 包锚点用 `derive_anchors(body, max_level=6)`——`##`~`######` 全进锚点，Agent 可按小节灵活召回（`pdf_reflow.py --write` 已内置）。全仓默认即 `max_level=6`（写入侧全层级细切，读取侧成本最小化）。**关键词部分整段一个锚点**（`## INDEX TERMS / 关键词` 一次唤起全部关键词）。
- **综述可检索**：`summary` 落关键事实首行，确保 L1 `query` 能命中。
- **上下文纪律（防记忆污染 / 窗口腐烂）**：写 `-review` 时，Agent 只读到「能写出靠谱综述」的体量——**绝不把全文（如 500+ 行 orig）驻留 / 重读进自己的上下文**；`-orig` 交确定性拷贝脚本（如 `python scripts/core/archive_paper.py orig <pdf>` 或 `pdf_reflow.py --write`），Agent 不手抄。入库后**稳态检索严格走** `query`(L1 只扫 id/title/summary/tags + 四要素 person/topic/location) → `query_anchors`(L2 章级) → `read_section`(L3 单 `##`)，**绝不把 `.md` 全文重读进上下文**。

## 对话记录分支（会议 / 访谈 / 对话流：逐字 + 拍板）

> 适用：用户给一段对话 / 会议记录 / 访谈 transcript，或口语说"把这场对话存一下""记一下刚才的会"。
> 核心交付：单包，含 `summary`(谈话背景) + `## 对话原文`(逐字) + `## 关键内容`(拍板) + C+A 双锚点 + `person` + `tags`(由关键内容派生)。
> 落点：`memory/对话/<主题或会议名>/`（新增顶层命名空间，详见 `存储架构总览.md` §4）。

### 流程
1. **判定与取文**：确认是对话 / 会议 / 访谈类；transcript 由你读取或用户贴文。记录元信息：主题 / 会议名、参与方、时间。
2. **定位路径**：`memory/对话/<主题或会议名>/`（如 `memory/对话/项目A进度会/`）；可按项目 / 主题嵌套，引擎子孙检索已支撑。
3. **拆成 1 个事件包**（字段级纪律见上方「Front-matter 落库契约」与 SCHEMA.md §2 范本，packs_template.md 为 inline 可抄模板）：
   - `summary` = 谈话背景（这场在聊什么，短、不混入结论）。
   - `person` = 参与方（dict 形态，如 `{"Alex": [], "assistant": []}`；会议填与会者，每人一个规范名键）。
   - `## 对话原文` = 逐字 transcript，每轮 `时间戳 | 对话人：对话内容`。
   - `## 关键内容` = 这场对话**最后拍板 / 确定的事**，每条 `时间戳 | 决定内容`（清水决策层，默认返回粒度）。
   - `anchors` = 两段 C+A 锚点（对话包标准样式，查「讨论过程」落对话原文、查「拍板了什么」落关键内容）：
     ```yaml
     anchors:
       - Chapter: 对话原文
         about: 本场逐字讨论的要点（议题/分歧/未决项）
         keywords: [讨论, 议题, 分歧]
       - Chapter: 关键内容
         about: 本场最后拍板/确定事项要点
         keywords: [拍板, 决定]
     ```
     ⚠️ V2 锚点无 `locator` / `tags` 字段，用 `Chapter` 定位、`keywords` 承载章级关键词（满足 5 维完整性契约）。
   - `tags` = **由 `## 关键内容` 每条决定派生的决策主语 / 规范实体**（单一真相源，不手工另写）；严禁当词袋全塞。
4. **落库（确定性 sink = 直写 `memory/`）**：
   ```bash
   cd hma && python -m hma.cli --root memory/对话/<主题> write \
       --id <主题>-<轮次或日期> --title "<会议/对话标题>" --summary "<谈话背景（2~4句自包含概述）>" \
       --tags "<由关键内容派生的实体>" --person "<参与方>" \
       --anchors '[{"Chapter":"对话原文","about":"本场逐字讨论要点（议题/分歧/未决项）","keywords":["讨论","议题","分歧"]},{"Chapter":"关键内容","about":"本场最后拍板/确定事项要点","keywords":["拍板","决定"]}]' \
       --body-file /tmp/<主题>.md
   ```
   等价 `Memory(root).write(...)`。手填上方两段 C+A 锚点（about 承载该节要点，是 pageIndex 选章的语义信号）；不手填则引擎按 `##` 派生（about 取章首句）。
5. **记当日账（daylog，叙事型）**：落库后给当天单日记录包追加一段叙事，`--linked` 指向本次对话包。
6. **回报（含归类开口）**：列出包 id / 路径 / 关联；落点是 AI 推断的须带归类开口句式（"当前归类为 `<路径>`…"）。

### 对话记录分支纪律（铁律）
- **关键内容 ≠ 对话原文**：关键内容是「清水决策层」，只放最后拍板 / 确定的事；对话原文是逐字全量，不切碎。两者不同轴不合并。
- **tags 由关键内容派生（单一真相源）**：`关键内容` 是唯一手写真相源，`tags` 永远由其派生、不手工另写，根除双写漂移（细则见 `SCHEMA.md`）。
- **矛盾 / 反向更新**：每场会议独立成包；引擎忠实保留相左事实、都检索得出来，是否矛盾由 AI 理解层判定，**绝不在写入时静默覆盖**旧决定（细则见 `SCHEMA.md`）。
- **person 非 agent 标识**：agent 标识不入库（由目录承担）；`person` 只记人类参与方 + 是否含 AI。

## 时间描述唤起（读侧）
用户用时间描述回忆时（"我前天干了些什么""那天是不是让你做过 XXX"）：
1. 你（Agent）把时间语解析成 ISO 日期 / 区间（"前天" → 今天减 2；不确定就问）。
2. 确定性查询：
   ```bash
   # daylog 读取无独立 CLI：经 hma.daylog 模块的 read_day(<date>) / days_in_range(...) 取叙事
   # 写入经 scripts/core/daylog_append.py（见上方「记当日账」）
   ```
3. 需要细节时，沿话题条目的 `linked` id 用 MCP 工具 `memory_read_section` / `memory_query_anchors` 调主题包正文（一对一映射）。时间只是过滤键，不做新鲜度加权。

## 纪律（铁律，不得违反）
- **内容即数据**：只写 `memory/` 下的事件 `.md`（经 `python -m hma.cli --root memory/<scope> write ...` 或 `Memory(root).write(...)`）；不写生产记忆。`index.db` 是可由 `.md` front-matter 重建的薄缓存，可随时 `rebuild`，但 `.md` 才是权威、永不丢弃。
- **长文不压缩**：原文多长就写多长进 `body`；细粒度召回靠锚点，不切碎。
- **确定性归引擎、理解归你**：你只产出"包结构"，落库 / 索引 / 关联由引擎做。
- **隐私**：真实敏感内容**不要写进 `memory/`**；机密内容留在仓库外，记忆里只记一句指向（如「详见 ~/private/xxx.md」，见 packs_template）。

## Reference
- `references/ingest_prompt.txt`：拆分规则（对齐 `hma/ingest.py:build_prompt`，保证与未来 LLM 后端同构）。
- `references/packs_template.md`：`packs` 模式源文件模板。
- `scripts/core/pdf_reflow.py`：PDF 确定性重排管线（双栏顺序恢复 + 原样校验），文章·资料分支的 PDF 源必走。
- `scripts/core/archive_paper.py`：原文包确定性拷贝（`orig` 模式），不手抄全文、防上下文污染。
- 路由入口：`aimh-intake`（判类型）→ 本技能；角色类 → `oc-dossier`（store 分支）。
