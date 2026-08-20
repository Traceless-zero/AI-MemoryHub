---
name: aimh-recall
description: >
  HMA 读取侧主动调度技能（read-dispatch / proactive recall）。当用户在对话中顺带提及某个
  具体实体——人名、OC 角色、物件/圣物、项目名、日期、主题词——且可能已落在 HMA 长期记忆中时，
  自动触发一次廉价检索（零 LLM、BM25、无成本）并取回精确锚点段落，把回答接地到记忆而非凭空编。
  是对 aimh-always「主动取」的硬触发补完：除显式"回忆X/查一下Y"外，覆盖 incidental mention
  （顺带提及也触发）。命中即接地并标注来源包；未命中静默照常。与 aimh-always 互补，可被其路由。
---

# HMA 读取侧调度：实体提及即 recall（aimh-recall）

> 这是 HMA 记忆能力的**读取侧闭环**：写入时把"泥潭变清水"（结构化录入），读取时让 AI
> **主动 consult** 这缸清水——用户一提到某个已落库的实体，就自动取回精确段落接地。
> 类比 `oc-dossier` 的 wake 分支（叫到 OC 名字就加载），本技能把同一机制泛化到**一切**
> 记忆实体（宝石、项目事实、过去决策……），不再只限角色。

## 触发判定（何时 firing）

满足任一即触发一次轻量 recall：

1. **顺带提及具体实体**：话里出现专有名词 / 具体物件 / 项目名 / 日期 / 主题词，
   且听感上"这东西可能我之前记过"。例："那颗黄蓝色大宝石""上周定的架构方向""维罗妮卡的导师"。
2. **显式回忆信号**：用户说"回忆X""查一下Y""之前我们是不是聊过Z""还记得吗"（继承 aimh-always 的 B 类）。
3. **连贯决策前**：要做依赖历史的判断，先确认 HMA 是否已有相关记忆。

**不触发**：纯闲聊 / 一次性计算 / 与任何已存实体无关的通泛提问。

> 触发成本极低（BM25、零 LLM、本地 SQLite），可高频 fire；未命中静默放过，不打断对话。

## 路径定位（首次 / 路径失效时跑，禁止推理猜路径）

复用 aimh-always 的路径协议：

1. 读指针文件 `~/.hma_home`（一行 = 仓库根绝对路径）；存在且含 `memory/` → 直接用。
2. 缺失/失效 → 跑 `python <repo>/scripts/core/where.py --json` → 取 `memory` 绝对路径，并登记 `~/.hma_home`。
3. 都不可得 → 问用户仓库在哪，拿到后跑 `where.py` 登记。

拿到后，下文 `<root>` = `where.py` 报出的 `memory` 绝对路径；CLI 一律 `cd <仓库根>` 下执行。

## 检索例程（确定性、零 ML）

```bash
# L2 锚点级精确召回（推荐，默认在当前包作用域；--all 全局扫描）
python -m hma.engine query_anchors <root> "<实体>" --all

# 包级定位（拿规范键 id / 标题，用于确认命中包）
python -m hma.engine query <root> "<实体>" --all
```

- `<实体>` 直接用具名原文（如 `黄蓝色大宝石`），引擎做确定性子串/分词匹配。
- `--all` = 全局扫描（`package_id=""`），跨包找实体；指定 `--package <pkg_id>` 则只扫某包。
- 输出：`(pkg_id, anchor_title, about, chapter, score)`；`(no match)` 即未命中。（V2 锚点无 locator/summary，用 about + Chapter 定位）

> 等价 Python API（已验证可用，适合在脚本里调）：
> ```python
> from hma_core import Memory
> mem = Memory(<root>)                      # root=某个包目录，db 自动落在 memory/ 祖先
> # 默认返回 list[(pkg_id, title, about, chapter, score)]（V2：locator 已改为 Chapter 定位键）
> hits = mem.query_anchors("<实体>", top_k=3, use_field_weights=True)
> # 开拒答层：召回不足时返回结构化 dict 而非硬凑结果
> res = mem.query_anchors("<实体>", top_k=3, allow_abstain=True)
> # res == {"answer":[...], "abstain":False, "reason":"", "confidence":"high"/"low"}
> #       或 {"answer":[], "abstain":True, "reason":"empty_pool"/"low_coverage"/"out_of_scope", "confidence":"none"}
> mem.close()
> ```

## 理解层关键词提取（真·功能接口 · 优先于机械拆词）

`query_anchors` / `resolve_query` 内置的 CJK 二元拆词只是**无 AI 接线时的兜底**，
顶不动复合实体（"量子计算""回旋镖"会被拆碎）与地面缺失误判。**正确路径是你
（理解层）先把自然语言问句解析成复合实体词，再经 `keywords` 传入**——这才是
「AI 负责理解、引擎负责确定性检索与拒答」契约的落点。

- **MCP 工具 `memory_query_anchors` / `memory_resolve` 现已支持 `keywords: string[]`**。
  调用前先做一步：从用户问句抽实体（如 "量子计算的最新进展是什么" →
  `["量子计算","最新进展"]`），随调用传入。传入即启用 `corpus_missing_entity`
  硬拒答闸：判别实体在语料（正文+锚点）查不到 → 直接拒答，不再依赖 coverage 兜底。
- 域内题的判别实体必在语料 → 不会误拒；域外题（库里没有的实体）→ 正确拒答。
- **机械拆词兜底永不该被当成主力**：它只在没有 AI 解析结果时生效，用于不接 LLM
  的轻量场景。凡接了理解层，一律优先 `keywords`。

### REFINE（Q 桶真空/多跳的兜底，理解层职责）

P 桶（查询自洽）引擎已 100%；**Q 桶（真空/多跳，实体需跨上下文消歧或 linked-BFS
+ REFINE 路由）零-ML resolver 不预期 100%，失败属「逻辑必然」，应交 REFINE**。

- REFINE = 一步常识桥接：把表面上查不到的细节词映射到语料里真实存在的主题词，
  再据此重新检索（如 "最值钱" → "宝石" → 命中「圣保罗之焰」）。
- 生产 REFINE 由 LLM 完成（输入 query → 输出关联实体词）；无 LLM 时可退化到
  零-ML 同义词词典兜底（`hma/refine.py: dict_refine_decomposer`，经
  `memory_resolve` 的 `decomposer=` 注入）。
- 多跳路由用 `memory_resolve(multihop=true)`：先沿 `linked` 双向 BFS 扩簇，再跑
  实体歧义门（机制复用），比裸 `memory_query(multihop=true)` 多一层歧义判定。

## 拒答层（faithfulness gate，务必开启）

召回**必须**带 `allow_abstain=true`（MCP 工具 `memory_query_anchors` 的可选参数；
Python API 同名字段）。三道确定性闸门（零 ML、免费）：

- `empty_pool` —— 候选池为空（BM25 完全无命中）。
- `low_coverage` —— top 锚点的 IDF 加权覆盖度 < κ（默认 0.34，即查询词权重的 1/3 以上未出现在最佳命中里）。
- `out_of_scope` —— 查询解析出已知四要素实体（人物/地点/主题/日期），但召回包的四要素零命中（忠实战落地「四要素字段缩圈」）。

**铁律**：当工具返回 `(ABSTAIN: <reason>) 记忆中无匹配，请勿编造` 时，
**直接告诉用户「记忆里没有这个 / 我不确定」**，**绝不**基于空结果编造、补全或假装命中。
理由（reason）只供你判断为何拒答，不要原样念给用户。
置信 `confidence="low"`（覆盖度在 κ~high 之间）时答案仍可用，但优先做一轮 refine 再回答。

## 命中后接地（Grounding）

1. 取回的锚点 `anchor_summary` 即精确段落摘要；如需完整正文，读该包 `.md` 对应 `##` 章节
   （`mcp__aimh__memory_read_section <pkg_id> "<anchor_title>"`）。
2. 把回答**基于**取回内容，并标注来源包（如「（据 HMA · sao-paulo-flame）」）。
3. 多命中时按 score 取 top；不要堆砌，只接最相关的 1–3 段。

## 未命中处理（Silent miss）

`(no match)` 或空结果 → **静默放过**，照常凭上下文回答，不报错、不卡流程。
这正是"廉价零成本检查"的设计：命中就接地，不命中零代价。

## 护栏（Guardrails）

- **隐私排除**：`veronica` / `private` 等私有包绝不外泄或误召回；命中私有包时按 aimh-always 的 C 类不碰。
- **不重复 fire**：同一实体同一回合不重复 recall；避免在长对话里反复查同一词。
- **不替代写**：本技能只管"取"，落库仍走 aimh-ingest / oc-dossier / aimh-project。
- **内容即数据**：取回即权威源（`.md`），索引可由 front-matter 全量重建，无需怀疑一致性。

## 与 aimh-always 的关系

`aimh-always` 是常驻入口与软策略（"有记忆意识"）；`aimh-recall` 是其**硬触发分支**——
把"实体提及 → 检索 → 接地"做成可触发的确定动作。两者互补：aimh-always 管"何时该想记忆"，
aimh-recall 管"想了之后怎么精确取"。路由见 aimh-always 路由表「实体顺带提及 → aimh-recall」。
