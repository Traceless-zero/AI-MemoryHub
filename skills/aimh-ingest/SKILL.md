---
name: aimh-ingest
description: >
  把通用文本 / 笔记 / 日志 / 文章 / 资料 / 想法存入 HMA（Hybrid Memory Architecture）
  长期记忆时，本技能定义「Agent 即理解层」的零成本收录流程。三分支：
  通用（本文件）/ 文章·资料（references/branch-paper.md，产 orig+review 一对）/
  对话记录（references/branch-dialog.md，产逐字+拍板单包）。
  何时用（命中即加载）：记一下、存进记忆、收录这段、存个笔记、记住这个、写进记忆、
  HMA、长期记忆、ingest、note、整理成记忆、论文、文章、文献、综述、归档这篇、
  读懂这篇、对话、会议、访谈、对话记录、把这场会存一下；
  凡用户给一段非角色类文本、要求存入 HMA 记忆库时，先加载本技能。
  注意：内容明显是「角色 / OC 档案」时改加载 oc-dossier（store 分支）。
---

# HMA Ingest（Agent 即理解层，零成本）

## Overview
把**通用文本 / 笔记 / 文章 / 资料**录入 HMA。落库是「确定性 + 可重建索引」的：**你（当前会话 Agent）充当理解层**——把文本拆成 CEMA 凝聚性事件包、生成元数据、发现关联；引擎负责确定性落库与索引。**无需任何 API key，零成本**。

> **同构可替换后端**：日后配置了真实 LLM（`OPENAI_API_KEY` + `HMA_LLM=openai` 等），`note` 模式自动改用 `hma/llm_adapter.py` 付费/本地路径，产出与本技能**完全相同**的包结构。两条路共用同一套引擎落库，互不冲突。

## 路由（先判断，再动手）
- 文本明显是"一个角色 / OC 档案"（用户说"存个角色"，或含 姓名 + 形象 + 行事调性 + 背景）：**加载 `oc-dossier`（store 分支）**，不在本技能手拆 OC。
- 论文 / 文章 / 长文资料，且意图含"归档 + 理解 / 综述 / 读懂"：**读 `references/branch-paper.md` 并从头跑到尾**（产 `<主题>-orig` 原文包 + `<主题>-review` 理解综述包一对）。
- 会议 / 访谈 / 对话流（逐字 transcript，或"把这场对话存一下"）：**读 `references/branch-dialog.md`**（产「谈话背景 + 逐字对话原文 + 拍板关键内容」单包）。
- 否则走下方「通用收录流程」。

> ⛔ **分支流程住在 references/ 里**：选中分支必须**把那个文件读完再动手**——
> 停在本文件里凭印象硬套分支流程 = 流程违规（会漏掉分支内的机械步骤与铁律）。

## 模块路由（用户/项目 按模块增补，不混不散）
收录**用户自身数据 / 项目工程数据**时，按模块落点、对已有模块包做"增补/覆盖"而非新建单体。这是 HMA「活文档整合 / 无限拆分」原则（拆分由凝聚性+体积触发）的落地。详见 `SCHEMA.md` §4；项目工程拆包细节召回键：`["项目包体拆包"]`。

**用户数据默认模块**（落 `memory/用户/<模块>/`，q-2 铁律：主语是用户本人）：
- `偏好`：稳定偏好 / 习惯 / 工具风格选择
- `方法论`：可复用的工作/思考方法、"以后这么做"
- `身份锚点`：自我描述 / 角色定位 / 长期身份事实
- `踩坑`：具体教训、易错点（与方法论互补）
- `事实`：与项目无关的稳定个人事实

**项目工程默认模块**（落 `memory/项目/<项目名>/`，README 式功能拆包，一个 md 一类职责）：
- `需求清单`（显式标 已完成/未完成）· `项目结构`（只描述目录布局，**严禁塞铁律/约定/架构决策**）· `开发日志`（按时间的工程记录）· `约定`（铁律/协作约定单独成文件）· 其余按需；某块涨到该拆再拆，**不提前建空包**

**日志/（daylog）仅装闲话 + 大事件简介 + 关联**：结构化项目跟踪进 `项目/<项目>/` 对应包，不进 daylog；daylog 靠 `linked` 挂碎片，自己不承载真相。

**落点决策**（配合步骤 2 一次比对 index）：
- 内容命中某模块语义域 → **增补进该模块包**（update 同包，不新建），除非该包已过大（体积触发）→ 在该模块下拆子包/子事件 id。
- 跨模块的新主题 → 按「嵌套逻辑关系」新建模块包。
- **绝不**：把不同模块内容塞进一个包；为小内容强行预建一堆空模块包。

## Front-matter 落库契约（唯一真相源：SCHEMA.md）

> ⚠️ **列表/字典字段可 inline JSON 单行 或 block 换行式**（引擎 `_parse_fm` 均正确解析，不再静默读丢）。
> 完整权威契约见 `memory/项目/AIMH-design-journal/SCHEMA.md` §2（落库与 `scripts/core/lint_memory.py` 校验的唯一真相源）。本技能不内嵌规则副本，避免漂移。
> 任何落库（通用 / 文章·资料 / 对话记录 / OC）都须遵守；**禁写 `id` / `aliases` / `features` / `created` / `updated`**。

### 照抄范本
完整可抄范本：`skills/aimh-ingest/references/packs_template.md`（inline 版）或 SCHEMA.md §2.8。要点速记：
- **11 必填字段齐备**：title/summary/tags/linked/anchors/person/event_date/location/topic/pkage_created/pkage_updated；无内容写 `[]`/`{}`，`event_date` 无时间信息写哨兵 `"—"`（仍标量，不用 `""`）；不省略整行、禁 `none`/`null`/`""` 字面值。
- **anchors** 唯一形态 `[{Chapter, about, keywords}]`，无 `locator`/`tags`；`keywords` 满足 5 维（时间/地点/关键事件/锚定物品/人物 各 ≥1 token）。
- inline 与 block 均可落库；推荐 block（人读直观、diff 友好）。

### 落库方式（推荐 new_package.py 全链路：骨架 → 填充 → fail-closed 校验落盘）
- **推荐：`scripts/core/new_package.py`**——① `--print-dict --type <类型>` 拿 dict 模板（类型：通用/对话记录/论文orig/论文review/疾病，文本块按分支规范定制）；② AI 填好 JSON + 正文 → `--fill fm.json --body-file body.md` 走 `validate_fm`/`render_fm` 确定性落盘，**校验不过不落盘（fail-closed）**；③ 骨架模式（无 --fill）直接出类型化脚手架 .md 供手填。默认拒绝覆盖已存在包；路径软检查（memory/ 内 + R59 中文提醒）。落盘后紧接 rebuild（脚本会打印提醒）。
- **改既有包（增补/归并/修字段）**：`new_package.py --export <md>` 拆出 fm.json + body.md → AI 编辑两文件 → `--import <md> --fill fm.json --body-file body.md` fail-closed 写回（`pkage_updated` 自动改今天，`--keep-updated` 可保留；旧式裸 dict FM 导出时自动归一为规范 list[dict]）。
- **或直写 `.md`**——按上方范本写好 `memory/<scope>/<id>.md`，再 `python scripts/core/rebuild_index.py --no-gui` 重建索引（格式风险自担）。
- **或 Python `Memory(root).write(...)`**——`person`/`location`/`topic` 传 dict、`event_date` 传字符串、`anchors=[{Chapter,about,keywords}]`；`pkage_created`/`pkage_updated` 经 `created`/`updated` 入参落盘；**不要传 `aliases`/`features`**（V2 已折进四要素）。
- 旧 CLI `write --id --title ...` 旗标**会丢四要素 / pkage_ 时间戳**，仅适合极简包；正式落库请用 new_package.py 或直写 .md。

## 通用收录流程

> 每步带召回键 → 权威：`memory/项目/AIMH-design-journal/拆包与收录规范.md`；召回 ABSTAIN → 停止上报，勿即兴。

1. **定位 root（落库目录）**：通用笔记/想法 → `memory/notes`；项目相关 → `memory/<project>`；外部主题/资料 → `memory/其他/<主题>/`；用户自身数据 → 按模块路由落 `memory/用户/<模块>/`（q-2 铁律）；用户指定 scope 则优先用。

   **嵌套逻辑关系（通用纪律）**：新建文件夹路径须**按内容的逻辑从属嵌套生成，不要摊平**。例：尼采综述 → `memory/其他/哲学/尼采/`，其下原文包 + 理解综述包互链；OC 同理 `原创角色/<角色>/`。引擎 `query(package_id=...)` 支持**前缀/子孙检索**（scope="哲学" 命中 "哲学/尼采" 子树），嵌套不破坏检索。
   · **命名语言（R59 用户拍板）**：**新建文件夹一律用中文**——中文路径的检索/锚点/互链已全链路实测无碍。唯一开口：用户主动要求英文、或内容处于明显英文语境（如英文论文按原名归档）。顶层命名空间已汉化（用户/项目/原创角色/日志/其他/对话）。
   召回键：`["通用收录流程"]`

2. **⛔ 一次比对 index（硬闸门：不跑完本步，禁止进入第 3 / 4 步落库）**：
   ```bash
   python -m hma.engine query <root> "<关键词/标签>"
   ```
   只取 id / title / summary（不扫正文），**一次**分出两类：
   - **归并候选（merge_candidate）**：某已有**包**与本次内容高度同构、疑似"同一事物"。
   - **关联事件（linked）**：相关但非同物。
   查重（防碎片）与查关联（防孤立）合并成一次 query。两者皆空则正常新建、不强关联。
   > ⛔ **跳过本步 = 流程违规**：2026-08-28 血泪——未跑比对就手搓建包，靠运气才发现 AIMH 早有权威版，险些造出重复碎片包。该命令已实测可用；跑不通先排错，**不要跳过**。
   召回键：`["通用收录流程"]`（同 §2，含比对 index 全流程）

3. **你（Agent）理解并拆分 + 决定落点**：遵循 `references/ingest_prompt.txt` 规则拆成 1+ 个 CEMA 凝聚性事件包。若步骤 2 有 `merge_candidate` 且你判断确为同一事物 → **归并**（写进该已有包，不新建）；否则按「嵌套逻辑关系」新建。每包产出（front-matter 严格按上方契约）：
   - `id`：仅作 `.md` 文件名 slug（kebab-case、全局唯一、保留中文，建议 `<scope>-<短主题>`），**不是 front-matter 字段**。
   - `title` / `summary`（2~4 句自包含真概要）/ `tags`（2–5 个）/ `linked`（复合 id）/ `anchors`（{Chapter,about,keywords}）/ 四要素 / `event_date` / `pkage_*`
   - `body`：markdown 正文（`# 标题` 开头）
   - 跨包关联：仅当与步骤 2 发现的 `linked` 或**本次同批新建包**真正相关时记链接（复合 id）。
   **严禁**：多个无关主题塞一个包；编造不存在的 id 做关联；写 `id`/`aliases`/`features`/`created`/`updated` 等已废除字段。
   召回键：`["拆包触发铁律"]`（拆分边界）

4. **落库（确定性 sink = 直写 `memory/`）**：按契约写好 `.md` 落 `memory/<scope>/<id>.md`，再 `python scripts/core/rebuild_index.py --no-gui` 重建索引（等价 `Memory(root).write(...)`，见上方「落库方式」）。V2 要求**显式写 anchors**（5 维关键词），不要留空让引擎盲派。

5. **记当日账（daylog，叙事型，收录即写）**：
   ```bash
   cd scripts/core && python daylog_append.py --title "<一句话小标题>" --linked "<本次落库的包id>" --tags "<2-4个关键词>" --body "<一段叙事：这天发生的一件事/一个进展，用'先是/随后/最后'连接，不要写成关键词卡片>"
   ```
   单日包 id 为 `daylog-YYYY-MM-DD`，默认落 `memory/日志`。一次收录 = 一段叙事；勿合并多次收录。`--linked`/`--tags` 是索引侧车，不影响叙事可读性。

6. **⛔ 主动输出「收录钩子」（= 落库完成的最后一步 / 完成标记）**：落库 + 日志完成后**必须**固定输出：
   > **📥 已收录至 `<package_id>`**（新建 / 归并进 `<已有包>`）。
   > · 相似已有包：`<merge_candidate 或 "无">` —— 若本就该合并，回复 **「合并 <已有包>」** 触发移包技能。
   > · 关联：`<linked 列表 或 "无">`。
   > · 如需改归到其他路径，回复 **「移包 <目标路径>」** 触发移包技能。
   钩子是"告知 + 可触发"，不阻塞、不追问；用户不回应 = 默认接受当前落点。
   ⚠️ 这是全流程**唯一**给用户纠错机会的出口（合并/移包），**绝不能省**——省掉它等于让用户失去一键纠偏入口。

## 时间描述唤起（读侧）
用户用时间描述回忆时（"我前天干了些什么"）：
1. 你把时间语解析成 ISO 日期/区间（"前天" → 今天减 2；不确定就问）。
2. daylog 读取无独立 CLI：经 `hma.daylog` 模块的 `read_day(<date>)` / `days_in_range(...)` 取叙事（写入经 `scripts/core/daylog_append.py`）。
3. 需要细节时，沿话题条目的 `linked` id 用 MCP 工具 `memory_read_section` / `memory_query_anchors` 调主题包正文（一对一映射）。时间只是过滤键，不做新鲜度加权。

## 纪律（铁律，不得违反）
- **内容即数据**：只写 `memory/` 下的事件 `.md`（经 `python -m hma.cli --root memory/<scope> write ...` 或 `Memory(root).write(...)`）；`index.db` 是可由 `.md` front-matter 重建的薄缓存，`.md` 才是权威、永不丢弃。
- **长文不压缩**：原文多长就写多长进 `body`；细粒度召回靠锚点，不切碎。
- **确定性归引擎、理解归你**：你只产出"包结构"，落库 / 索引 / 关联由引擎做。
- **隐私**：真实敏感内容**不要写进 `memory/`**；机密内容留在仓库外，记忆里只记一句指向（如「详见 ~/private/xxx.md」）。

## Reference
- `scripts/core/new_package.py` —— **骨架生成 + fail-closed 落库首选入口**（--print-dict / 骨架模式 / --fill；类型化文本块，见「落库方式」）
- `references/branch-paper.md` —— 文章·资料分支（论文/长文：orig + review 一对，含 PDF 确定性管线）
- `references/branch-dialog.md` —— 对话记录分支（会议/访谈：逐字 + 拍板单包）
- `references/ingest_prompt.txt` —— 拆分规则（对齐 `hma/ingest.py:build_prompt`，与 LLM 后端同构）
- `references/packs_template.md` —— packs 模式源文件模板（inline 可抄范本）
- `scripts/core/pdf_reflow.py` / `scripts/core/archive_paper.py` —— PDF 确定性重排/拷贝管线（用法见 branch-paper）
- 路由入口：`aimh-intake`（判类型）→ 本技能；角色类 → `oc-dossier`（store 分支）
