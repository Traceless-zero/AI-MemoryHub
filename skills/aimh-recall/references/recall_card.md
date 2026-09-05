# AIMH 召回卡（会话常驻 · 由 SessionStart hook 注入）

> 本卡是 `skills/aimh-recall/SKILL.md` 的操作核压缩，由读卡 hook 装载。
> 口径冲突以 SKILL.md 为权威；完整例程（REFINE / 多跳 / 路径协议）加载 aimh-recall 技能。

## 何时查（任一即查；BM25 本地检索零成本，未命中零代价）

1. 顺带提及具体实体（人名 / OC 角色 / 项目名 / 物件 / 日期 / 主题词），且可能已落库
2. 显式回忆信号（"回忆X""查一下Y""之前是不是聊过Z"）
3. 做依赖历史与记忆的判断、决策之前

纯闲聊 / 一次性计算 / 与任何已存实体无关的通泛提问 → 不查。

## 怎么查（构查纪律——禁止拿整句当 query）

- 先从问句**抽出实体词**，经 `keywords: string[]` 传入 `mcp__aimh__memory_query_anchors`
  （包级定位用 `mcp__aimh__memory_query`）。例："量子计算的最新进展" → `["量子计算","最新进展"]`
- 传入 keywords 即启用硬拒答闸（corpus_missing_entity）；引擎内置 CJK 拆词只是无理解层时的兜底，**永不作为主力**
- **必须带 `allow_abstain=true`**。CLI 兜底：`python -m hma.engine query_anchors <root> "<实体>" --all`（root 经 `~/.hma_home` / `where.py` 定位）

## 结果处理

- 命中 → 回答**基于**取回内容并标注来源包（据 HMA · <pkg_id>）；只接最相关 1–3 段；要全文用 `mcp__aimh__memory_read_section`
- 返回 ABSTAIN（empty_pool / low_coverage / out_of_scope）→ 直接说"记忆里没有 / 我不确定"，**绝不编造**；confidence=low 先 refine 再答
- 未命中 → 静默放过，照常凭上下文回答，不报错不打断
- **长尾细节**（无锚点位物件：「那张唱片什么样」类，锚点召回选不出段）→ `mcp__aimh__memory_obscure_recall`（obj_token=特征实体词，锁章人机共审；规范见 召回消歧管线 §13）

## 护栏

- 私有包（demo-char / private 等）不外泄、不误召回
- 同一实体同一回合不重复查
- 本卡只管"取"；落库走 aimh-ingest / aimh-daylog-archive 技能链，绝不手搓 memory/
