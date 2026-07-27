# HMA 意图路由表（单一真相源）

> 本表是 HMA 所有子技能路由的**权威依据**，单一来源、不复制。
> `hma-always`（常驻分发）与 `hma-intake`（前门元路由）都引用本表；改路由只改这一处。
>
> AI 判完用户意图后，按本表**加载对应子技能**。原则：**AI 只做理解分流，落盘交给子技能与 `hma.engine` CLI**（CEMA：理解归 AI、确定性归脚本）。

## 意图 → 子技能

| 用户意图 | 触发信号 | 路由到 |
|---|---|---|
| 存**通用**文本 / 笔记 / 日志 / 想法（含主动存信号） | "记一下""存进记忆" / 浮现持久事实 / 多轮沉淀结论 | **`hma-ingest`**（通用分支） |
| 存 / 摘**文章 / 资料 / 论文**（归档 + 理解综述） | "归档这篇""把论文收进记忆""读懂这篇" / 长文资料 | **`hma-ingest`**（文章/资料分支） |
| 存 / 摘一个 **OC 角色**（文字或文件） | "把这个角色存下来""从书里摘个角色""整理成 OC 档案" | **`oc-dossier`**（store 分支） |
| 对话中**叫到某 OC 名字**并像对其说话 | 出现已登记 OC 名字 + 像在对话 | **`oc-dossier`**（wake 分支） |
| 导入 **AI 客户端原生记忆**（WB / Claude Code / Gemini / Codex） | "把 XX 记忆收进 HMA""导入 XX 工作日志" | **`memory-import`** |
| **项目工程收录**（按 README 式拆包策略） | "把这个项目/模块收进记忆""按项目结构拆包" | **`hma-project`** |
| **归类纠错 / 移包 / 合并** | "移包 <目标>""合并 <已有包>""刚才归错了" | **`hma-relocate`** |
| **检索 / 回忆**（不存） | "回忆 X""查一下 Z" / 问题依赖过往上下文 | 直接调引擎（见下方「检索路径」） |
| **学怎么用 HMA（看操作手册）** | "用户操作手册""怎么用HMA""教我怎么用" | 引擎取 `用户操作手册` 包（见 `hma-always` 自唤起钩子） |
| 按名查 OC 档案（**不扮演**） | 提到某 OC 名字、想看它档案 | `python scripts/oc_registry.py find` + `python -m hma.engine query` |
| **更新路径**（HMA 目录搬了 / 换了盘） | "更新路径""路径变了""HMA 搬家了" | 跑 `python <新位置>/scripts/where.py` 刷新 `~/.hma_home` |

> 路由拿不准优先按"信号最强的那一个"走；若明显是角色类，即使没明说"存角色"也导向 `oc-dossier`（store）。
> 非记忆类闲聊 / 普通问答 → 不走任何子技能，正常回应（记忆能力不影响日常助手职能）。

## 检索路径（纯取，不触发收录）

```bash
python -m hma.engine query <root> "<关键词>"            # L1 包级（限当前 root 作用域）
python -m hma.engine query <root> "<关键词>" --all      # L1 跨所有包
python -m hma.engine query_anchors <root> "<锚点>"       # L2 章级锚点
python -m hma.engine read_section <root> <id> "<章节>"   # L3 取整章正文
python -m hma.engine 日志 show <YYYY-MM-DD> [--q ...]    # 时间轴
python scripts/oc_registry.py find "<原话>"              # OC 名字 → 基础包
python scripts/oc_registry.py list
```

## 路径路由（客户端原生记忆探测，交给 memory-import 前先收窄）

| 探测信号 | 客户端 | 适配器 |
|---|---|---|
| cwd 在 `~/.claude/projects/<hash>/` 下，或存在 `memory/` AutoMemory | Claude Code | `scripts/migrate_claude_memory.py` |
| 存在 `~/.gemini/GEMINI.md` | Gemini CLI | `scripts/migrate_gemini_memory.py` |
| 存在 `~/.codex/memories/` | Codex | `scripts/migrate_codex_memory.py` |
| 项目级存在 `.workbuddy/memory/2026-*.md` | WorkBuddy | `scripts/migrate_wb_memory.py` |

> 判定拿不准就问用户"你这次想导哪个客户端的记忆？"。路径探测只做"收窄候选"，最终落库与索引全交给 `memory-import`。

## 后台铁律（路由时务必遵守，源自 CEMA 设计）

- **前后台 1:1**：每个事件包恰一条索引记录；`.md` 是权威源，索引可由 front-matter 全量重建。
- **无状态确定性检索**：检索是确定性查询（关键词 / 锚点 / 时间过滤），绝不按热度 / 新鲜度加权。
- **AI 只理解，脚本确定性写**：理解 / 拆分 / 关联判断归 AI，落库 / 建索引 / 装卸交给 `hma.engine` CLI 与子技能。
- **内容即数据**：拆包触发条件是体积 / 凝聚性，不是作者写法。
- **OC 三层拆包铁律**（经 `oc-dossier`）：① 基础包必有且仅 1 个 = 姓名+形象+语气；② 背景超长自然分立「故事包」；③ 拓展包含则分、无则无。
- **项目 README 式拆包**（`hma-project`）：需求清单 / 项目结构 / 开发日志 / 约定 各成单独 `.md`；项目结构文件禁塞铁律，约定文件收"死规矩"。

## 收尾纪律（任何 AI 路线落库后）

任何经 AI 路线落库的操作（写 `.md` 后），收尾统一调用确定性重建入口（与手动双击同源）：
- 双击等价：`hma/一键更新记忆索引.exe`（无头环境设 `HMA_NO_GUI=1`）
- 等效无弹窗：`python scripts/rebuild_index.py`（AI 路线优先用这条）

> 索引永远只有一个真相来源；AI 路线不自己维护 index.db 的离散一致性。
