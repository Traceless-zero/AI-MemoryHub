---
title: 外部技术对照：AIMH vs 主流检索与记忆方案
summary: 渐进式对照档案——把 PageIndex、LLM Wiki、RAG 等外部检索/记忆技术的实现机制与 AIMH 的设计选择并排比较，凸显 AIMH 零 ML、BM25 确定性选章、理解力前置写时的差异化路线。PageIndex、LLM Wiki、RAG 已写完，GraphRAG/RAPTOR/Mem0/SAG 等条目待补。
tags: [ 对照, 外部技术, 竞品分析, PageIndex, RAG, LLMWiki, 零ML, 设计参照 ]
linked: [ 项目/AIMH-design-journal/AIMH核心规格（极简·当前实现）.md, 项目/AIMH-design-journal/SCHEMA.md ]
person: []
event_date: —
location: []
topic: [{"技术对照": ["RAG", "向量检索", "PageIndex", "LLMWiki"]}]
anchors:
  - Chapter: "1. 文档定位与用法"
    about: "本对照文档的目的与渐进式写法约定，以及和 AIMH 核心规格的关系"
    keywords: ["对照", "外部技术", "渐进写法", "AIMH", "设计参照"]
  - Chapter: "2. PageIndex：LLM 树搜索选章 ✅"
    about: "PageIndex = VectifyAI 团队 2026 年开源的 vectorless/reasoning-based RAG 框架（GitHub ~29k★，Thoughtworks 技术雷达纳入评估象限）；面向结构化长文档的精准检索，把文档变层级目录树让 LLM 沿树推理导航定位而非向量匹配；含 2.1 是什么/2.2 核心机制（离线建树+在线寻路 pageindex_search 函数 LLM 推理选章+回溯）/2.3 与 AIMH 对应维度/2.4 优势短板/2.5 架构结论。"
    keywords: ["PageIndex", "VectifyAI", "vectorless", "树搜索选章", "LLM推理导航", "2026开源", "结构化长文档"]
  - Chapter: "2.1 是什么"
    about: "PageIndex 是什么：VectifyAI 团队 2026 年开源的 vectorless/reasoning-based RAG 框架，定位面向结构化长文档（金融财报/法律合同/学术论文/技术手册）的类人化精准检索，宣称 FinanceBench 达 98.7% 准确率；一句话把文档变成层级目录树让 LLM 像专家翻书一样沿树推理导航定位而非向量相似度匹配。"
    keywords: ["PageIndex是什么", "VectifyAI", "vectorless", "结构化长文档", "FinanceBench", "目录树导航", "2026"]
  - Chapter: "2.2 核心机制——\"智能选章\"怎么实现的"
    about: "PageIndex 核心机制——智能选章怎么实现，分两段：离线建树（LLM 读取 PDF/Markdown 解析成层级 JSON 树，每节点含 title/node_id/页码范围/LLM 生成的 summary/递归子节点，按自然结构划分不切块）与在线寻路（pageindex_search 函数从根 while 非叶子，llm_reason 对各子节点 title+summary 做 CoT 推理选最多 3 分支输出 JSON，下钻重复，含回溯机制，终止后提取叶子完整原文喂 LLM 生成答案）。"
    keywords: ["核心机制", "离线建树", "在线寻路", "pageindex_search", "llm_reason", "回溯机制", "智能选章"]
  - Chapter: "2.3 与 AIMH 对应维度"
    about: "PageIndex 与 AIMH 对应维度对照表：选章主体（PageIndex 查询时调 LLM 推理 vs AIMH 引擎 BM25 确定性排名零 LLM）、章节摘要来源（PageIndex LLM 离线生成 vs AIMH 人类写时策展 about 字段 CEMA）、切块策略（都不切块保留自然结构）、是否向量（都无向量零 ML）、跨章节多跳（PageIndex LLM 树搜索 vs AIMH linked BFS 确定性）、可追溯性（PageIndex 推理路径迹 vs AIMH read_section 精确 Chapter 定位）。"
    keywords: ["对应维度", "选章主体", "摘要来源", "BM25确定性", "linkedBFS", "零ML", "可读溯源"]
  - Chapter: "2.4 优势 / 短板"
    about: "- PageIndex 优势：跨页多跳与对比题强；"
    keywords: ["跨页多跳"]
  - Chapter: "2.5 架构结论（对 AIMH 的意义）"
    about: "PageIndex 架构结论（对 AIMH 的意义）：旧 SCHEMA.md 曾把 pageIndex 选章误述为 AIMH 机制（把 LLM 查询时导航选章错误投射到 AIMH）；AIMH 刻意不把 LLM 放进检索路径、选章交 BM25 零成本、LLM 只作外部理解层；共性都先有章节摘要再选章且拒绝切碎保留结构，差异在摘要谁写选章谁做（PageIndex 全交 LLM、AIMH 前置人类策展+确定性排名）；结论 AIMH 不是缺选章能力而是用零 ML 路线达同类目的，PageIndex 从未在 AIMH 引擎实现且按设计哲学不该进引擎，反证核心规格不做清单。"
    keywords: ["架构结论", "误述修正", "BM25选章", "LLM不进检索", "零ML路线", "从未实现", "不做清单"]
  - Chapter: "3. LLM Wiki：知识编译范式 ✅"
    about: "Karpathy 提出的 LLM Wiki pattern——把 LLM 当知识编译器，原始文档进、结构化互链 Markdown wiki 出，无向量库无 embedding；与 AIMH 反向量/Markdown 为王/Obsidian 兼容/lint-health 同源，但 compile 是 LLM 生成新页、AIMH 是写时确定性策展。"
    keywords: ["LLM Wiki", "Karpathy", "知识编译", "反向量", "Obsidian", "compile", "零ML"]
  - Chapter: "3.1 是什么"
    about: "LLM Wiki 不是单一产品，是 Karpathy 的 LLM Wiki pattern + 多实现（stevenflyai/llm-wiki-web、omnipotence-eth/llm-wiki、nashsu/llm_wiki、llmwiki.app 托管）。核心：文件+LLM+Obsidian，无向量库无 embedding。"
    keywords: ["LLM Wiki", "Karpathy", "实现", "无向量"]
  - Chapter: "3.2 核心机制——知识编译"
    about: "compile 流水线：source→extract→LLM 生成结构化 wiki 页（摘要+互链+frontmatter）→写 md→cross-link；query 用 BM25 检索→LLM 合成答案→可选落为新页。Health/lint 查断链/孤儿页/缺失元数据/知识缺口。"
    keywords: ["compile", "BM25", "lint", "health", "互链"]
  - Chapter: "3.3 与 AIMH 对应维度"
    about: "同源：反向量、Markdown 为王、Obsidian 兼容([[backlinks]])、lint/health(AIMH 的 lint_memory/check_kw 同角色)；差异：compile=LLM 生成新页 vs AIMH 写时 CEMA 确定性策展、零-ML resolver。"
    keywords: ["对应维度", "反向量", "Obsidian", "lint", "CEMA", "零ML"]
  - Chapter: "3.4 优势 / 短板"
    about: "优势：知识随时间生长、全人类可读、Obsidian 图可视化、health 量化；短板：compile 依赖 API/花钱、生成页可能幻觉、多实现成熟度参差、引入外部依赖。"
    keywords: ["优势", "短板", "幻觉", "API", "成熟度"]
  - Chapter: "3.5 架构结论（对 AIMH 的意义）"
    about: "当哲学验证而非集成对象：Karpathy 独立得出\"文件+LLM+Obsidian、去向量\"，佐证 AIMH/kb-pilot 反 embedding 方向；AIMH 在确定性写入+四要素检索更硬，且 lint/health+graph 已自带，无需引入外部系统。"
    keywords: ["哲学验证", "反embedding", "确定性", "四要素", "不集成"]
  - Chapter: "4. RAG：通用向量 / 混合检索范式 ✅"
    about: "通用 RAG 范式——向量库+chunking+embedding+reranker 标准流水线，2026 主流转 hybrid（dense vector + BM25）；与 AIMH 对照：AIMH 零向量、用 BM25+四要素确定性软重排替代 semantic embedding，理解力前置写时而非查询时推给 LLM。"
    keywords: ["RAG", "向量库", "embedding", "chunking", "reranker", "混合检索", "BM25"]
  - Chapter: "4.1 是什么"
    about: "RAG = 检索增强生成，把外部知识检索喂给 LLM 生成接地回答；标准流水线：离线 chunk→embed→向量库，在线 query-embed→ANN top-k→(rerank)→prompt→LLM；2026 主流转 hybrid（dense+BM25）。"
    keywords: ["RAG", "检索增强", "标准流水线", "向量检索"]
  - Chapter: "4.2 核心机制——标准流水线"
    about: "离线：chunk 256-512 token+overlap→bi-encoder embed→向量库(FAISS/HNSW/IVF)；在线：query embed→ANN top-k→cross-encoder rerank→prompt augment→LLM。Advanced 补丁：Semantic Chunking、Query Transformation(HyDE/Multi-Query/Step-Back)、Two-Stage(Bi+Cross Encoder)。"
    keywords: ["chunk", "embed", "ANN", "rerank", "HyDE", "语义漂移"]
  - Chapter: "4.3 与 AIMH 对应维度"
    about: "检索：RAG 靠向量相似度(语义) vs AIMH BM25+四要素(词法+结构化)；理解时机：RAG 推到查询时(LLM rerank/HyDE) vs AIMH 前置写时(CEMA)；lost-in-middle/chunk-drift 痛点 AIMH 用锚点选章+四要素归一天然规避；rerank 同目标(AIMH 字段加权+锚点级确定性裁切，命中@5 89.7-92%)。"
    keywords: ["对应维度", "向量", "BM25", "四要素", "写时", "rerank"]
  - Chapter: "4.4 优势 / 短板"
    about: "优势：知识新鲜/减幻觉/可溯源/可扩展、生态成熟；短板：向量相似度≠相关(lost-in-middle)、固定 chunk 语义漂移、查询表述差致低精度、组件多故障点多、向量库+API 成本高、评估难。"
    keywords: ["优势", "短板", "lost-in-middle", "chunk-drift", "成本"]
  - Chapter: "4.5 架构结论（对 AIMH 的意义）"
    about: "当哲学验证+反面教材而非集成对象：RAG 的痛点(lost-in-middle/相似≠相关/chunk 漂移)正是 AIMH 用确定性写时策展解决的；AIMH 的 BM25+四要素重排已对齐 TrueMemory 93% 基线，无需引入向量库；hybrid 中 BM25 部分与 AIMH 同频。"
    keywords: ["哲学验证", "确定性", "相似≠相关", "不集成"]
  - Chapter: "5. AIMH 自身基准（对照基线）✅"
    about: "对照的前提是先有自己的数字：收拢已实测基准（两级召回/端到端/回归护栏/写入侧），标注机械路径下界 vs AI 流程生产。"
    keywords: ["AIMH自身基准", "对照基线", "两级召回", "机械路径", "AI流程"]
  - Chapter: "5.1 检索基准：两级召回 vs 全局 unscoped（32 题，真实库 29 事件）"
    about: "两级召回（先 query 锁包 → 再逐包 query_anchors）32 题真实库：recall@1 91% vs 全局 84%，P桶 recall@3/5 100%，误拒 0 vs 2；1029 事件规模树下两级 recall@5 94%，是无 AI 关键词的下界基线。"
    keywords: ["两级召回", "recall@1", "规模树", "误拒", "全局"]
  - Chapter: "5.2 端到端：LoCoMo"
    about: "LoCoMo 1540：recall@30≈99.5% / hit@5 89.7–92%，对齐 TrueMemory 93% 基线方向。"
    keywords: ["LoCoMo", "recall@30", "hit@5", "TrueMemory"]
  - Chapter: "5.3 回归护栏（引擎正确性核心，全部确定性可复现）"
    about: "bench_aimh_internal 16/16 加对抗 5/5、questionset 13/13、abstain 4/4、fm_schema_kw PASS、paper_camus 12/12、d2 8/8；demo-char 可答 20/20 对抗 4/5 机械边界；gem_attr 5/8 未归一拒答预期。"
    keywords: ["回归", "bench", "demo-char", "gem_attr", "机械边界"]
  - Chapter: "5.4 写入侧完整性与拒答层"
    about: "check_write_integrity 8/8、真实库 hard=0 soft=16；拒答层多道闸+MCP 默认开拒答；AI 接口对抗 5/5 硬拒。"
    keywords: ["check_write_integrity", "hard", "soft", "拒答层", "对抗"]
  - Chapter: "5.5 对照读法"
    about: "本节数字是 AIMH 与外部方案对照的自身基线；RAG 侧基准（TrueMemory 93% 等）测的是不同任务，不可直接并列；AIMH 数字用于验证确定性加澄清路线在自身任务上不掉链子。"
    keywords: ["对照读法", "自身基线", "跨范式", "不可并列"]
  - Chapter: "6. 待补对照清单 ⬜"
    about: "以下条目按统一结构补写（挑一项、写一项、翻状态）。"
    keywords: ["条目按统"]
pkage_created: 2026-08-18
pkage_updated: 2026-08-29
---

# 外部技术对照：AIMH vs 主流检索与记忆方案

> 本文档是**渐进式对照档案**：把外部世界的检索 / 记忆技术逐一拉进来，和 AIMH 的已实现设计选择并排比较。目的不是评优劣，而是**在对比中确认 AIMH 的路线边界**——哪些能力别人用 LLM/向量拿到、AIMH 用确定性 BM25 + 写时策展拿到；哪些是 AIMH 刻意不做的（零 ML 立场），而非"没实现"。
> 写法约定：每条外部技术单独成章，结构统一为「是什么 → 核心机制 → 与 AIMH 对应维度 → 优势/短板 → 架构结论」。已写完的标 ✅，待补的标 ⬜ 并留"待写什么"。
> 字段落库契约权威在 `SCHEMA.md`；本文件只做技术对照，不修改 AIMH 自身规格。

## 1. 文档定位与用法

- 适用读者：AIMH 设计者，需向外解释"我们和某某方案差在哪"时使用。
- 如何渐进补充：在 §6 候选清单里挑一项，新建对应章节、按统一结构写、把状态从 ⬜ 翻 ✅；不要一次写全（避免空想式铺陈，守住"文档只写验证了的东西"红线）。
- 与核心规格关系：`AIMH核心规格（极简·当前实现）.md` 是 AIMH 自身"当前真实实现"的唯一真相源；本文档是对外参照，不反向改写 AIMH 规格。

## 2. PageIndex：LLM 树搜索选章 ✅

### 2.1 是什么
- **PageIndex** = VectifyAI 团队 2026 年开源的 **vectorless / reasoning-based RAG** 框架（GitHub ~29k★，Thoughtworks 技术雷达纳入"评估"象限）。
- 定位：面向**结构化长文档**（金融财报、法律合同、学术论文、技术手册）的"类人化"精准检索，宣称在 FinanceBench 达 98.7% 准确率。
- 一句话：把文档变成层级"目录树"，让 LLM 像人类专家翻书一样**沿树推理、导航、定位**，而非向量相似度匹配。

### 2.2 核心机制——"智能选章"怎么实现的
分两段：

**离线建树（索引生成）**
- LLM（默认 GPT-4o）读取 PDF/Markdown，解析成层级 JSON 树；每个节点 = 一个章节，含：
  - `title`（章节标题）、`node_id`（唯一 ID）、页码范围（`start_index`/`end_index` 或 `page_index`）
  - **`summary`：LLM 生成的该章节摘要**
  - `nodes`：子章节（递归）
- 关键：按文档**自然结构**划分节点，不切块（no chunking），完整保留上下文语义。

**在线寻路（查询推理）** —— 这就是"智能选章"本体
- 函数 `pageindex_search(query, tree_root)`：从根节点开始 `while` 当前节点非叶子：
  1. `child_scores = llm_reason(query, current_node.children)` —— LLM 读取各子节点的 **title + summary**，做思维链（CoT）推理，判断哪个最可能含答案；
  2. 选取**最多 3 个**最相关分支（支持多分支避免遗漏），输出严格 JSON：`{"reason": "...", "selected_node_ids": [...]}` ；
  3. 下钻进入选中子节点，重复。
- **回溯机制**：若进入某节点发现无相关内容，自动回溯到父节点重选其他子节点。
- **终止条件**：到达叶子节点 / LLM 判断当前节点内容已足够回答 / 无相关子节点可选。
- 终止后提取选中叶子节点的**完整原文**（非碎片），按文档原生结构顺序聚合，再喂给 LLM 生成答案。

导航 Prompt 核心约束（示意）：
> 你是一名专业的文档检索专家，根据用户问题从以下文档节点中选择最可能包含答案的节点。【用户问题】…【可选子节点】node_id: 标题 - 摘要 … 要求：分析核心意图，最多选 3 个最相关节点并按相关性排序；先输出思考过程再输出 JSON。

### 2.3 与 AIMH 对应维度
| 维度 | PageIndex | AIMH |
|---|---|---|
| 选章主体 | **查询时调 LLM 推理**（每节点一次 `llm_reason`） | **引擎 BM25 确定性排名**（`query_anchors` 按 Chapter+about+keywords），零 LLM 在检索路径 |
| 章节摘要来源 | **LLM 离线生成**（建树时 GPT-4o 产 summary） | **人类写时策展**的 `about` 字段（CEMA：理解力前置到写入时） |
| 切块策略 | 不切块，保留自然结构 | 不切块，`##` 标题树即结构，正文按 Chapter 定位键取 |
| 是否向量 | 无向量、无向量库 | 零向量、零 embedding、零 ML |
| 跨章节/多跳 | LLM 树搜索天然支持跨页多跳 | `linked` BFS 多跳（确定性） |
| 可追溯性 | 推理路径迹（trace）可审计 | `read_section` 返回精确 Chapter 定位，可溯源 |

### 2.4 优势 / 短板
- **PageIndex 优势**：跨页多跳与对比题强；答案带精确推理路径，可审计（金融/法律刚需）；无向量库运维负担；对"相似≠相关"类长文档题表现好（宣称）。
- **PageIndex 短板**：① 建树慢且贵（依赖 LLM/文档，数百页需数分钟+API 费）；② 不适合碎片化多文档实时检索；③ 依赖原文档本身有清晰目录结构（扫描手写件效果差）；④ 查询时延/算力高（LLM 推理循环 + KV Cache）。

### 2.5 架构结论（对 AIMH 的意义）
- 旧 `SCHEMA.md` 曾把"pageIndex 选章"误述为 AIMH 机制——这是把 PageIndex 的**"LLM 在查询时导航选章"模型错误投射**到 AIMH。AIMH 刻意不把 LLM 放进检索路径，选章交给 BM25（确定性、零成本），LLM 只作外部理解/合成层。
- 二者**共性**：都"先有章节摘要（PageIndex 的 summary / AIMH 的 about），再据此选章"；都拒绝切碎碎片、保留结构。差异在**摘要谁写、选章谁做**——PageIndex 全交给 LLM（离线写摘要+在线做选择），AIMH 把摘要写作前置到人类策展、选章交给确定性排名。
- 结论：AIMH 不是"缺 PageIndex 的选章能力"，而是用另一条（零 ML）路线达到了同类目的。**PageIndex 从未在 AIMH 引擎实现，且按设计哲学本就不该进引擎**——这反证了核心规格"明确不做"清单第 1 条应写作"从未实现"而非"不做"。

## 3. LLM Wiki：知识编译范式 ✅

### 3.1 是什么
- **LLM Wiki 不是单一产品，是 Andrej Karpathy 提出的「LLM Wiki pattern」+ 多个社区实现**。核心一句话：**把 LLM 当"知识编译器"——原始文档进，结构化、互链的 Markdown wiki 文章出；无向量库、无 embedding，纯"文件 + LLM + Obsidian"**。
- 主要实现（成熟度参差，按需选型）：
  - `stevenflyai/llm-wiki-web` —— 个人 KB；compile / query / health-check / Web UI / Obsidian 集成；多 LLM provider（OpenAI、Anthropic、Azure、DeepSeek、Ollama）。
  - `omnipotence-eth/llm-wiki` —— CLI，git 版本化、零数据库、BM25 检索、多 provider 路由（Groq→Gemini→Ollama）。
  - `nashsu/llm_wiki` —— Tauri 桌面 App（Win/macOS/Linux），含「知识图谱」视图 + MCP server + Agent Skill。
  - `llmwiki.app` —— 托管版（Supabase 认证 + PostgreSQL + S3 + PGroonga 全文索引 + MCP）。
- 它明确对标传统 RAG：存储用结构化 Markdown（而非向量库）、知识随时间**生长**（而非无状态检索）、互链用 Obsidian `[[backlinks]]`（而非隐式相似度）。

### 3.2 核心机制——知识编译
**compile 流水线**（以 stevenflyai 实现为例）：
- `raw/`（PDF / PPTX / DOCX / MD）→ LLM 抽取 → 生成**结构化 wiki 页**（LLM 写的摘要 + 互链 + YAML frontmatter）→ 写 `wiki/*.md` → 自动 cross-link。
- 每页带 frontmatter（title / type / sources / tags / confidence），正文含 `## Related - [[其他页]]` 互链。
- **Query 流水线**：question → BM25 检索 → 取 top 页 → LLM 合成答案（带引用）→ 可选"若合成足够新颖则落为新 wiki 页"，把探索沉淀为持久知识。
- **Health / Lint**：查断链（broken `[[links]]`）、孤儿页、缺失元数据、知识缺口、INDEX 覆盖率，给 0–100 健康分。

### 3.3 与 AIMH 对应维度
| 维度 | LLM Wiki | AIMH |
|---|---|---|
| 存储基底 | 结构化 Markdown（wiki 页） | `memory/*.md`（源即权威 + `index.db` 薄索引） |
| 向量 / embedding | **无**（标语 "No vector databases, no embeddings"） | **零向量、零 embedding、零 ML**（resolver 端） |
| 知识组织 | LLM 生成 wiki 页 + `[[互链]]` | 四要素（person/event_date/location/topic）+ `linked` + 锚点 |
| 写入主体 | **查询/compile 时调 LLM 生成新页** | **写时确定性策展**（CEMA：AI 理解归一到四要素，脚本确定性写 `to_markdown`） |
| 检索路径 | BM25 取 top → LLM 合成 | BM25 + 四要素软重排 → READ(AI 读 topK) → REFINE → rerank（零 ML resolver） |
| 互链 / 图 | Obsidian `[[backlinks]]` + 知识图谱视图 | `linked` 字段（相对路径）；图可视化待零依赖静态 HTML 图实验（Task #150） |
| 健康检查 | lint（断链/孤儿/缺口/健康分） | `lint_memory` / `check_kw` / `check_kw_warn`（契约+LINT） |
| Obsidian 兼容 | 原生（wiki 即 Obsidian vault） | 可选：只读 vault + wikilink 桥接（未做，见 Obsidian 讨论） |

### 3.4 优势 / 短板
- **LLM Wiki 优势**：知识随源累积**生长**（compounding artifact）；全人类可读的 Markdown；天然 Obsidian 图可视化；health 分数量化知识库健康度；多 provider 路由（含本地 Ollama，零 API 费可选）。
- **LLM Wiki 短板**：① compile 依赖 LLM API（多数实现要 key / 花钱，生成步骤有成本）；② LLM 生成页**可能幻觉**（故设 Review 队列让人终审）；③ 多实现成熟度参差（早期 CLI / 桌面 App / 托管），要接得先选型且带外部依赖；④ 生成式 wiki 页与"源文档"是两层，溯源链比 AIMH 的"源即权威"多一跳。

### 3.5 架构结论（对 AIMH 的意义）
- **当作"哲学验证"而非"要集成的工具"**。LLM Wiki 与 AIMH 在三条主线上同源：**反向量/反 embedding**（连 Karpathy 这种量级的人都独立得出"文件+LLM+Obsidian、去向量"）、**Markdown 为王 + 源即真理**、**Obsidian 兼容 + lint/health 自检**。这直接佐证 AIMH / kb-pilot 放弃向量库、坚持确定性写入的方向**不是走偏**——外部已有重量级同类实践。
- **但 AIMH 在关键维度更硬，且已自带对应能力，无需引入**：① 写入上 AIMH 是 CEMA 写时确定性策展（四要素归一/消歧、源内容不被动），LLM Wiki 是 LLM 生成式 compile（偏"文档自动摘要器"），二者路线不同、AIMH 的确定性更强；② 检索上 AIMH 是零-ML resolver（BM25+四要素+REFINE），LLM Wiki 检索仍要 LLM 合成；③ `lint_memory`/`check_kw` **已覆盖** LLM Wiki 的 health/lint 角色；④ 图谱需求用上一条"零依赖静态 HTML 图"即可补，不必为此引入 Obsidian/LLM Wiki 外部系统。
- 结论：**方向和 Karpathy 同频，实现上 AIMH 更克制、更零依赖**。把它写进对照是为了（a）对外解释时有个强背书锚点，（b）明确"我们不缺它"——避免晚期在 P1/P2 债未清时叠外部复杂度。

## 4. RAG：通用向量 / 混合检索范式 ✅

### 4.1 是什么
- **RAG（Retrieval-Augmented Generation，检索增强生成）** = 把"外部知识检索"喂给 LLM，让它基于检索到的上下文生成接地、可溯源的回答，而非只靠训练记忆。核心解决三件事：知识时效性（不重训即可更新）、幻觉（grounded in 源）、数据隐私（知识留本地基础设施）。
- **标准流水线（Naive RAG）**：离线把文档切块 → embed 成向量 → 存向量库；在线把 query embed → ANN 检索 top-k →（可选 rerank）→ 拼进 prompt → LLM 生成。公认三大组件：retriever（向量检索）/ knowledge base（向量库）/ generator（LLM）。
- **2026 主流转向 hybrid search**：纯 dense vector 不够，生产系统普遍把 dense vector + BM25 keyword 混合，同时处理"语义"与"精确匹配"；cross-encoder reranker 单独一步可提升答案质量 20–35%（基准）。

### 4.2 核心机制——标准流水线
**离线索引阶段（一次性 / 更新时）**
- `Stage 1 Chunk`：原始文档切 256–512 token 窗口 + 10–20% overlap（Naive）；Advanced 用 Semantic Chunking（按句间 embedding 距离找语义断点）。
- `Stage 2 Embed`：bi-encoder（OpenAI text-embedding-3、bge-m3、MiniLM 等）把 chunk 编码成 dense 向量。
- `Stage 3 Index`：存进持久向量库（FAISS / HNSW / IVF，或 Chroma / Pinecone / pgvector），附带元数据（source / page / date）供查询时过滤。

**在线查询阶段（每次查询）**
- `Stage 4 Retrieve`：同一 encoder 把 query 编码，ANN 检索 top-k（k=5–20）候选。
- `Stage 5 Rerank`（可选但推荐）：cross-encoder 对 query+doc 联合打分，重排到 k'=3–5。
- `Stage 6 Generate`：top 候选拼进 prompt（"只用以下上下文回答，不在就答不知道"）→ LLM 生成带引用的回答。

**Advanced RAG 补丁（针对 Naive 的三大失效）**
- *Lost-in-the-Middle*（LLM 忽视长上下文中部）→ 上下文压缩 / 动态 chunk 排序 / 硬截断 rerank。
- *Semantic Drift*（固定 chunk 切破句子/逻辑块）→ Semantic Chunking + Parent-Document 检索。
- *Low Precision / High Recall*（query 表述差）→ Query Transformation：HyDE（先生成假想答案再 embed）、Multi-Query（改写 3–5 变体）、Step-Back Prompting（先抽抽象概念）。
- 两阶段检索：Bi-Encoder 快取 top-K，Cross-Encoder 精排（精度换延迟）。

### 4.3 与 AIMH 对应维度
| 维度 | RAG（通用 / hybrid） | AIMH |
|---|---|---|
| 检索基底 | **向量相似度**（semantic embedding，dense vector） | **BM25 + 四要素确定性软重排**（词法 + 结构化），零向量 |
| 理解时机 | **查询时推给 LLM**（rerank / HyDE / query rewrite） | **前置到写入时**（CEMA：AI 写时归一/消歧/四要素策展） |
| 切块 | chunk 256–512 + overlap（Naive 痛点：语义漂移） | 不切块，`##` 标题树即结构，Chapter 定位键取正文 |
| "相似≠相关" 处理 | 靠 reranker 修正（仍概率性） | 四要素精确名宇宙 + 字段权重（person>time>loc>topic），确定性 |
| lost-in-middle | 真实痛点，靠压缩/重排缓解 | 锚点选章只取命中 Chapter 原文，无长上下文中部问题 |
| 拒答 / 防幻觉 | prompt 指令"不在就答不知道" | 拒答层 `_abstain` + `corpus_overlap_absent` 门（已修 over-abstain） |
| rerank 目标 | cross-encoder 重排 top-k | 字段加权 + 锚点级 dK 确定性裁切；命中@5 89.7–92%，对齐 TrueMemory 93%（包级 rerank 装置默认关） |

### 4.4 优势 / 短板
- **RAG 优势**：知识新鲜（不重训）、减幻觉（grounded + 引用）、数据留本地（隐私）、可扩展（易加源）、生态极成熟（LangChain / LlamaIndex / 4600+ 工具）、对"无结构化长文本语料"开箱即用。
- **RAG 短板**：① **向量相似度 ≠ 相关**（semantic drift，相似块未必答对）；② **lost-in-the-middle**（长上下文中部信息被忽视）；③ **固定 chunk 语义漂移**（切破句子/逻辑块稀释含义）；④ **查询表述敏感**（query 差 → 低精度，需 HyDE/改写补）；⑤ **组件多 = 故障点多**（chunk/embed/index/rerank 任一段坏都崩）；⑥ **成本高**（向量库 + LLM API 持续计费）；⑦ **评估难**（比简单 Q&A 难量化）。

### 4.5 架构结论（对 AIMH 的意义）
- **当"哲学验证 + 反面教材"而非"要集成的工具"**。RAG 的三大类痛点（lost-in-the-middle / 相似≠相关 / chunk 语义漂移）**正是 AIMH 用确定性写时策展规避的**：AIMH 不切块、理解力前置到写入（四要素归一）、检索走 BM25+四要素软重排而非向量相似度——这些 RAG 要靠 reranker/HyDE/压缩去"修补"的问题，AIMH 在架构层就不存在。
- **AIMH 已对齐 RAG 的 rerank 目标，且更省**：AIMH 的 BM25 rerank 命中@5 达 89.7–92%（对齐 TrueMemory 93% 基线），与 RAG 的 cross-encoder rerank 同目标、不同手段——AIMH 用确定性词法重排而非概率向量，零 embedding 成本。
- **hybrid search 里的 BM25 部分与 AIMH 同频**：2026 RAG 主流已承认"纯向量不够、必须混合 BM25 关键词"——这恰好印证 AIMH "词法 + 结构化"路线的正确性，等于业界在用另一种方式回归 AIMH 早就走的路。
- 结论：**方向不缺、能力不缺、无需引入向量库**。把 RAG 写进对照是为了（a）对外解释"我们为什么不用向量库"时有标准靶子，（b）明确 AIMH 的零-ML 路线不是简陋替代，而是对 RAG 已知痛点的结构性规避。

## 5. AIMH 自身基准（对照基线）✅

> 对照的前提是先有自己的数字。本节收拢 AIMH 已实测的基准与回归数据（截至 2026-08-19），并标注**机械路径**（bench 无 AI 理解层，是下界基线）与 **AI 流程**（生产路径，AI 给 keywords）之别。复现入口：`scripts/tests/bench_aimh_internal_groups.py`（`AIMH_TWO_LEVEL=1` 开两级召回）、`scripts/tests/regress_*.py`、`scripts/tests/bench_*.py`。

### 5.1 检索基准：两级召回 vs 全局 unscoped（32 题，真实库 29 事件）

| 指标 | 全局 unscoped | 两级召回（先 query 锁包 → 再逐包 query_anchors） |
|---|---|---|
| recall@1 | 84%（27/32） | **91%（29/32）** |
| recall@3（P 桶 25 题） | 88% | **100%** |
| recall@5 | 94% | **100%** |
| 误拒（over-refusal） | 2 | **0** |

- 规模干扰：1029 事件规模树（≈1000 包强干扰）下两级 recall@5 = **94%**（8/16 修复后记录）；bench 注释明确这是**无 AI 关键词的下界基线**。
- 机械路径 P 桶的 2 题 over-refusal（「AIMH 项目名历史上用过哪些叫法」「AIMH 的拒答层底层怎么判断该拒答」）在 **AI 流程**（AI 给 `keywords`）下全部解除——印证「机械保底、AI 精度」分工。

### 5.2 端到端：LoCoMo

- LoCoMo 1540：**recall@30 ≈ 99.5% / hit@5 89.7–92%**，对齐 TrueMemory 93% 基线方向。

### 5.3 回归护栏（引擎正确性核心，全部确定性可复现）

- bench_aimh_internal **16/16 + 对抗 5/5** 全绿；regress_questionset 13/13；regress_abstain 4/4；regress_fm_schema_kw 全 PASS；regress_paper_camus 12/12；regress_d2_ai_abstain 8/8；test_resolve_refine 7/7；test_demo-char_queries 8/8；test_wake_resolve 6/6。
- bench_demo-char_20_5：可答 **20/20**；对抗 **4/5**（鲁迅《故乡》机械路径漏拒 = 已知机械边界；**AI 接口路径 5/5 硬拒**）。
- regress_gem_attr **5/8**：蓝钻 / 深海蓝橙焰 / 那颗钻石 未归一 → **拒答**（预期行为：未归一别名诚实拒答；补变体即 8/8）——这正是「写入归一 → 召回；未归一 → 拒答」闭环的回归证据。

### 5.4 写入侧完整性与拒答层

- `check_write_integrity`：test_write_integrity **8/8**；真实 memory 只读 lint（20 实体）：**hard=0**（规范名均唯一）/ **soft=16**（拥挤邻域预警有效）。
- 拒答层：`_abstain` 多道闸（空池 / 语料包含性 / 覆盖不足 / 越界 / 零重叠）+ `corpus_missing_entity` 硬闸；MCP 层默认 `allow_abstain=True`；API 层默认 False（测试 / 编排隔离，分层设计）。

### 5.5 对照读法

- 本节数字是 AIMH 与外部方案对照的**自身基线**：RAG 侧基准（TrueMemory 93%、FinanceBench 98.7% 等）见对应章节——注意它们测的是不同任务（开放域 QA / 结构化长文档），**不可直接并列**；AIMH 数字用于验证「确定性 + 澄清」路线在自身任务上不掉链子，而非跨范式比拼。

## 6. 待补对照清单 ⬜

以下条目按统一结构补写（挑一项、写一项、翻状态）。每条"待写什么"已列，避免空想铺陈：

- **（建议候选，待用户点名再补）**：GraphRAG（图谱+社区摘要）、RAPTOR（递归层级摘要树）、Mem0 / Zep（面向 agent 的自组织记忆）、SAG（SQL+向量事件结构，见设计 journal 既有研究）等。

---

（文档随对照条目增长而扩展；每次只补已验证/已确认的内容。）
