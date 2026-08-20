# AI记忆中枢（AI-MemoryHub）

> 零依赖、模型无关的 AI Agent 长期记忆系统：Markdown 正文作权威源 + 薄 SQLite 索引，用确定性检索替代向量 RAG，把"理解"交给外层 AI、引擎只做检索与拒答。基于 CEMA（Cognitive Event-driven Memory Architecture，认知-事件驱动记忆架构）概念构建。

> 个人项目，vibe coding 独立开发：架构与需求设计由本人完成，代码由 AI 辅助实现。

---

## 项目介绍

AI记忆中枢（AI-MemoryHub）把"长期记忆"拆成两层：

- **后台正文（权威源）**：每个记忆是一个 Markdown 文件，带 YAML front-matter，存全部语义内容。永不参与检索，按需按 ID 取用（即"被遗忘的冷存储"）。
- **前台索引（薄 SQLite 表）**：存 `id / title / summary / aliases / tags / linked / anchors / created / updated` + `features`（子实体变体归一）+ 四要素 `person / event_date / location / topic`，可由所有 `.md` 的 front-matter **全量重建**。检索只发生在这里，命中唯一 ID 后才取正文。

这套设计称为 CEMA（前台薄索引 + 后台正文，前后台严格 1:1、索引可由正文全量重建）——**无状态检索、廉价存储不遗忘**，且卸下了传统记忆系统的运维重量（无向量基建、无夜间 LLM 流水线、Agent 直写）。

设计为**零第三方依赖**（仅 Python 标准库），可对接任意 AI 大模型 API，理解层由 AI 客户端 / Agent / 付费 LLM 任一承担。

> **命名约定**：本文档中「AI记忆中枢（AI-MemoryHub）」为本项目正式名称；「HMA」专指其底层架构 Hybrid Memory Architecture（混合记忆架构）。代码中的 `hma` 包名、MCP server 名、`HMA_LLM` 环境变量等标识符保持不变。

### 核心特性

- **事件化记忆**：事件为唯一载体，不按短期/长期、情景/语义分类
- **前后台严格分离**：薄 SQLite 索引 + Markdown 正文，索引可由 front-matter 全量重建
- **不遗忘、全保留**：无重要性评分、无遗忘曲线，判断留给检索时
- **反向量猜测的确定性召回**：零向量/零嵌入；F-stage 子实体变体归一 + C+A 章级消歧 + READ 取正文 + 循环查询
- **Tag 即 Mod 的包级装卸**：复制/删除 memory 下文件夹 = 装卸一块认知
- **模型无关**：通用 LLM 适配器，今天 Claude、明天 GPT、后天本地 Ollama 都不用改代码
- **查询契约强制**：MCP 边界对每次检索做 QueryEnvelope 校验（缺 `keywords`/`mode` 直接挡回）

> 架构哲学、检索分类与解决思路见 `memory/项目/AIMH-design-journal/` 下的设计文档；**MCP 工具清单、引擎 API、检索机制、适配器、设计不变量、基准口径** 全部收敛到 **[`技术参考.md`](memory/项目/AIMH-design-journal/技术参考.md)**。本文档只讲「是什么 / 怎么跑」。

---

## 项目结构

> `memory/` 是 AI记忆中枢（AI-MemoryHub）的**单一权威存储**。每个记忆包 = 一个 `.md` 事件文件（`##` 标题树 + YAML front-matter）+ 包内 `index.db`（薄索引缓存，可由 `.md` front-matter **全量重建**，删了不丢数据）。

```
AIMH/
├── hma/                          # 引擎核心（零运行时依赖，仅标准库）
│   ├── hma_core.py             # Memory 类：write/query/query_anchors/resolve_query/read_section/link/rebuild/orchestrate/list_all_in_scope/ingest + derive_anchors/query_features/recall_multihop
│   ├── envelope.py             # QueryEnvelope 校验层（MCP 边界强制）
│   ├── cli.py                  # 命令行入口
│   ├── server.py               # MCP server（stdio JSON-RPC，8 工具）
│   ├── engine/                # 分支接口 / CLI（dispatch + @register + handlers）
│   ├── ingest.py              # AI 收录管线
│   ├── daylog.py / tree.py / llm_adapter.py
├── scripts/core/               # 独立确定性脚本（rebuild_index / relocate / migrate_*_memory / compact / deploy_mcp …）
├── skills/                      # 技能（项目级副本，与用户级 ~/.workbuddy/skills 双副本）
├── memory/                      # 权威记忆库（单一真相）
├── 一键更新记忆索引.exe          # 手动重建索引小程序（双击即用，零 AI）
├── pyproject.toml               # 零运行时依赖声明
└── README.md
```

---

## 执行流程

### 安装

```bash
pip install -e .          # 提供 hma-mcp / hma 两个命令
```

`pyproject.toml` 声明**零运行时依赖**（仅标准库）。无需任何向量库或外部服务。

### 三种用法

#### 1. 命令行（人工 / 脚本）

```bash
python -m hma.cli --root memory write \
  --id proj-rag --title "放弃 RAG 主记忆" --summary "改事件驱动分层" \
  --tags project,decision --aliases "分层记忆" --body "# ...\n正文"

python -m hma.cli --root memory query "分层记忆" --top-k 5
python -m hma.cli --root memory link proj-rag todo-mcp
python -m hma.cli --root memory show  proj-rag
python -m hma.cli --root memory list
python -m hma.cli --root memory rebuild      # 删了 index.db 也能恢复
```

#### 2. MCP server（接任意 AI 客户端）⭐ 推荐

```bash
python -m hma.server --root memory
# 或 entry point： hma-mcp --root memory
```

`stdio` 上的 JSON-RPC 2.0，暴露 **8 个工具**（对应三级检索漏斗 L1→L2→L3 + 写入/关联/重建/收录）：

| 工具 | 作用 |
|:---|:---|
| `memory_write` | 被动结构化写入一个事件包（id 存在则覆盖） |
| `memory_query` | L1 包级确定性检索，返回 Top-K 候选（命中 ID） |
| `memory_query_anchors` | L2 章级锚点检索，按 `##` 标题精确定位某轮/某节（返回 locator） |
| `memory_resolve` | 召回消歧统一入口：多实体时澄清，否则返回 Top-K；支持多跳 + 拒答闸 |
| `memory_read_section` | L3 取正文：按 (id, heading) 只读该 `##` 段，零冗余 |
| `memory_link` | 双向关联两个事件包 |
| `memory_rebuild` | 从 `.md` 全量重建索引（`.md` 是权威源，不丢数据） |
| `memory_ingest` | 主动收录：用户贴一段文本，AI 跑完整管线（见下） |

Claude Desktop / Codex / Cline / WorkBuddy 等任何 MCP 客户端，加一段配置即可：

```json
{
  "mcpServers": {
      "aimh": {
        "command": "python",
        "args": ["-m", "hma.server", "--root", "/path/to/.memory"]
      }
  }
}
```

**WorkBuddy 即插即用部署**：仓库自带一键部署脚本，把启动器复制到 WorkBuddy 配置目录、合并写出 `~/.workbuddy/mcp.json`（只动 `aimh` 连接器、保留其它、自动探测 python 版本、不写死路径），并登记 `~/.hma_home` 指针：

```bash
python scripts/core/deploy_mcp.py            # 部署（幂等，可重跑）
python scripts/core/deploy_mcp.py --dry-run  # 只预览将写出的配置
```

部署后在 WorkBuddy 连接器管理页点「信任」激活 `aimh` 连接器，新窗口即出现 `mcp__aimh__*` 工具。
> ⚠️ 改 `server.py` 后需在连接器里禁用→启用 / 重新 Trust，长驻进程才加载新代码。

#### 3. 作为库（Python `import`）

```python
from hma.hma_core import Memory
m = Memory("memory")
m.write(id="x", title="X", summary="s", tags=["t"], body="# X\n正文")
for rid, title, summary, score in m.query("x"):
    print(rid, score)
```

### 写入与收录

**主动收录（`memory_ingest`）**——用户贴文本，AI 执行完整管线：读取现有包摘要做关联发现 → 按 CEMA 凝聚性+体积闸门拆分为事件包 → 为每个包生成元数据 → 写入 .md 权威源 + upsert 索引 → 与现有/新建包建立双向关联。未配置 LLM API 时退化为单包启发式，工具永远可用。

```bash
# 有 LLM：AI 自动拆分+关联
echo "周会：放弃 RAG，改事件驱动；下周三前完成 MCP 评审。" \
  | python -m hma.cli --root memory ingest --scope wb

# 无 LLM / 不想调模型：单包兜底
echo "随手记一条想法" | python -m hma.cli --root memory ingest --no-llm
```

**零成本路径（Agent 即理解层）**：未配置 key 时，让当前会话 Agent 充当理解层（加载 `aimh-ingest` 技能），由确定性引擎落库——与付费 LLM 路径同构可替换。当文本类型不确定时，先加载 `aimh-intake` 元路由技能做分类决策，再链式加载 `oc-dossier` / `aimh-ingest` / `aimh-project` / `memory-import` 对应技能落库，自己不写任何 `memory/` 文件。

**付费/本地路径**：设 `HMA_LLM`（并配好对应 key/端点）即自动改走 `llm_adapter` 真实 LLM，无需改任何代码；LLM 调用失败会自动退回启发式。

### 时间轴：单日记录包（daylog）

主记忆库按**主题而非时间线**组织；`daylog` 补上正交的时间轴，不破坏主题原则：

```bash
python -m hma.engine daylog add "一段叙事：这天发生的事" \
    --linked 主题包id --tags 关键词1,关键词2 [--date 2026-07-25]
python -m hma.engine daylog show 2026-07-25            # 全天
python -m hma.engine daylog show 2026-07-25 --q 关键词  # 精准搜寻
python -m hma.engine daylog range --start d1 --end d2
```

时间是**过滤键不是权重**（定位 = id 内嵌日期的确定性比较，不做新鲜度加权）。模糊时间语（"前天/上周三"）由 Agent 解析成 ISO 日期后再调命令。

### 上下文压缩归档（昼夜节律 · Agent 即理解层）

当上下文窗口将满时，把已讨论完、暂未落库、但以后可能要用的溢出内容，由 Agent 判定落点 + 生成冷凝摘要，确定性写交 `scripts/core/compact.py`：

```bash
python scripts/core/compact.py \
    --root memory --sink <daylog|cache|progress> \
    --summary "<冷凝摘要>" --source "<溢出来源>" \
    [--date YYYY-MM-DD] [--id <eid> --title "<标题>"] [--project <pid>] \
    [--linked a,b] [--tags x,y] [--conflict-event <id> --conflict-intro "<一句话>"]
```

铁律：压缩 = **加法式冷摘要**，权威原文一字不动；仅当新信息与某权威事件**真正冲突**时才覆盖并追加可审计 trail。

### 迁移外部记忆

`scripts/core/` 下的 `migrate_wb_memory` / `migrate_claude_memory` / `migrate_gemini_memory` / `migrate_codex_memory` 把各 AI 客户端的原生长期记忆迁移进 AIMH，装上可检索的 CEMA 前台索引：

```bash
python scripts/core/migrate_wb_memory.py     --wb-dir ".workbuddy/memory" --root memory/项目/AIMH-design-journal
python scripts/core/migrate_claude_memory.py  --root memory --namespace 其他
python scripts/core/migrate_gemini_memory.py  --root memory --namespace 其他
python scripts/core/migrate_codex_memory.py   --root memory --namespace 其他
```

> 迁移脚本完整清单与哲学见 **[`技术参考.md` §八](memory/项目/AIMH-design-journal/技术参考.md)**。

### 进阶检索（scope / 拒答 / 多问 / 枚举）

写时与读时的几档增强机制，详见 **[`技术参考.md` §七](memory/项目/AIMH-design-journal/技术参考.md)**：

- **聚焦 `scope`**：传入目录路径只召回该子树，屏蔽跨子树干扰（29 包 → 11 包），只收束范围不替拒答。
- **拒答层 `allow_abstain`**：覆盖不足/域外查询显式返回拒答，避免编造（V1.0 已落地，默认开）。
- **多问 `sub_queries`**：AI 一次给子问清单，引擎确定性扇出合并，不单独往返。
- **枚举 `enumerate`**：列出 scope 子树内全部包（非 Top-K 排序）。
- **多跳 `multihop`**：沿写入时策展的 `linked` 边 BFS 扩簇，补关系/结构盲区（opt-in）。

所有检索类 MCP 调用都受 **QueryEnvelope 契约**约束（`q`/`keywords`/`mode` 必填，缺则 `ENVELOPE_VIOLATION` 挡回）。

---

## 当前状态

> **项目状态（2026-08-20）**：因 LLM 资源（免费模型额度）耗尽，本项目正式结项，开发阶段结束。代码、文档与基准数据保持当前状态不变；挂起事项（如 LoCoMo 全量跑分）在有可用资源时可随时恢复续跑。

**定位**：零依赖参考实现 + 个人哲学试验场——把事件化记忆、前后台分离、不遗忘、反向量猜测等设计在零依赖下做了工程验证，并接入召回检索四要素、F+C+A+READ 三段式锚点管线、LoCoMo / MemoryStress 基准评测。

**已兑现的哲学**：事件化记忆 · 前后台严格分离 · 不遗忘全保留 · 反向量确定性召回 · Tag 即 Mod 包级装卸 · 跨窗口离线整合（昼夜节律）。

**工程状态**：
- 零第三方运行时依赖（仅 Python 标准库）
- MCP server 暴露 **8 工具**（write / query / query_anchors / resolve / read_section / link / rebuild / ingest）
- 召回检索四要素（person / event_date / location / topic）已为一等字段，读取期软加权
- 锚点级检索已升级为 **F+C+A+READ 三段式**（生产引擎已闭环）
- **拒答层 V1.0 已落地**（四道闸 + `corpus_missing_entity` 硬拒，`allow_abstain` 默认开）
- **QueryEnvelope 契约已落地**（MCP 边界强制 `q`/`keywords`/`mode`，多问扇出 `sub_queries`、枚举 `list_all_in_scope`）
- 技能作为即插即用客户端 + 常驻主动触发技能（aimh-always）

**基准评测（已跑通真实数据闭环）**：

- LoCoMo 1540 题：hit@30 ≈ 99.6% / recall@30 ≈ 99.5% / hit@5 89.7–92%
- MemoryStress 300 题：`baseline` 77% / `B_gold` 89.7%

> 完整口径（含红线：OMEGA 38.3% 不可并列、TrueMemory 93% 作对齐目标）见 **[`技术参考.md` §九](memory/项目/AIMH-design-journal/技术参考.md)**。

**已知缺口**：
- 窗口内实时活文档整合重置（边对话边把碎片整合进既有正文）在当前 Transformer 架构下做不出完整版，留待非 TF 架构（持久状态 SSM/Mamba 类，或真 AGI）
- MCP 连接器需在客户端点「信任」激活
- 引擎 API 直接调用绕过 MCP 边界的 QueryEnvelope 约束（预期隔离，测试脚本走 API 不受影响）
- **架构权衡（能力上限在 AI 层）**：CEMA 把理解力（归约/判 mode/抽 keywords/拆 sub_queries/策展 linked）集中押在 AI 层，引擎只做确定性执行。收益是引擎极小、可调试、随 AI 升级白赚；代价是 **AIMH 的质量上限 = 配对 AI 的智能上限**——AI 弱则退化为「偶尔用错的漂亮文件柜」。三道缓冲（信封硬校验/写时策展摊销/拒答闸兜底）把「AI 可能笨」变为「可控且可纠正」，但不消除该上限。详见《召回消歧的数学与语言哲学思路》§11.5。

## License

MIT
