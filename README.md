# AI记忆中枢（AI-MemoryHub）

> 基于 HMA（Hybrid Memory Architecture，混合记忆架构）构建 · Markdown 正文 + 薄 SQLite 索引 · 零依赖、MCP 可插拔、模型无关。

> **命名约定**：本文档中「AI记忆中枢（AI-MemoryHub）」为本项目正式名称；「HMA」专指其底层架构 Hybrid Memory Architecture（混合记忆架构）。代码中的 `hma` 包名、MCP server 名、`HMA_LLM` 环境变量等标识符保持不变。

AI记忆中枢（AI-MemoryHub）把"长期记忆"拆成两层：

- **后台正文（权威源）**：每个记忆是一个 Markdown 文件，带 YAML front-matter，
  存全部语义内容。永不参与检索，按需按 ID 取用（即"被遗忘的冷存储"）。
- **前台索引（薄 SQLite 表）**：只存 `id / title / summary / aliases / tags / linked`，
  可由所有 `.md` 的 front-matter **全量重建**。检索只发生在这里，命中唯一 ID 后才取正文。

这套设计称为 CEMA（前台薄索引 + 后台正文，前后台严格 1:1、索引可由正文全量重建）——**无状态检索、廉价存储不遗忘**，且卸下了传统记忆系统的运维重量（无向量基建、无夜间 LLM 流水线、Agent 直写）。

设计为**零第三方依赖**（仅 Python 标准库），可对接任意 AI 大模型 API。

---

## 项目结构

> `memory/` 是 AI记忆中枢（AI-MemoryHub）的**单一权威存储**。每个记忆包 = 一个 `.md` 事件文件（`##` 标题树 + YAML front-matter）+ 包内 `index.db`（薄索引缓存，可由 `.md` front-matter **全量重建**，删了不丢数据）。所有写入路径都直接落 `memory/`

```
hma/
├── hma/                          # 包：核心库 + 固定引擎
│   ├── hma_core.py             # Memory 类：写/读/关联/检索/重建 + 变更事件钩子
│   ├── daylog.py               # 单日记录包：时间轴索引层（叙事 → 关联 ID → 主题包）
│   ├── ingest.py               # run_ingest 主动收录管线（接 LLM 适配器时由模型理解拆分）
│   ├── llm_adapter.py         # 通用大模型适配器（OpenAI 兼容 / Anthropic，模型无关）
│   ├── cli.py                  # 命令行入口：write/query/link/show/list/rebuild
│   ├── server.py               # MCP server（stdio JSON-RPC：memory_write/query/link/rebuild/ingest）
│   └── engine/               # 内容即数据的固定引擎
│       ├── dispatch.py        # 通用引擎入口：modes / derive / query / query_anchors / install / uninstall / rebuild-all / tree / daylog
│       ├── anchor_derive.py   # 章级锚点确定性派生器（扫 ## 标题树）
│       ├── registry.py        # @register(mode) 分支接口 + HANDLERS 字典
│       ├── handlers/         # mode 实现（import 即自注册）
│       │   ├── packs.py      # mode=packs：显式事件包清单（最通用）
│       │   ├── oc_dossier.py # mode=oc_dossier：dossier → 3 层铁律切片
│       │   └── note.py      # mode=note：原始文本 → ingest 管线
│       └── tree.py           # 生成 memory/ 目录结构树.md（派生缓存）
├── skills/                       # 技能文件
│   ├── oc-dossier/            # OC 角色档案：存（判定+切片/AI拆包）+ 唤醒（按名扮演）一体
│   ├── hma-ingest/            # 主动收录：Agent 理解层 + 直写 memory/（通用 + 文章/资料 两分支）
│   ├── hma-intake/           # 通用前门 / 元路由：判定类型 → 链式加载对应技能
│   ├── hma-project/           # 项目工程收录：README 式功能拆包（需求/结构/日志/约定）
│   ├── memory-import/         # 客户端原生记忆 → AI记忆中枢（Claude Code / Gemini / Codex 适配器）
│   └── hma-archive/          # 上下文压缩归档（昼夜节律 · Agent 即理解层）
├── scripts/                      # 常驻、可运行的工作脚本（技能依赖）
│   ├── where.py               # 路径自报/自定位（"第一公里"；登记 ~/.hma_home 指针）
│   ├── mcp_launch.py          # MCP 启动器（canonical，零写死，自定位 memory/）
│   ├── deploy_mcp.py          # 一键部署 AI记忆中枢 MCP 连接器到 ~/.workbuddy（幂等）
│   ├── oc_registry.py          # OC 名字 → 包 确定性解析器（实时扫 memory/）
│   ├── migrate_claude_memory.py # Claude Code AutoMemory → AI记忆中枢（AI-MemoryHub）
│   ├── migrate_gemini_memory.py# Gemini CLI 持久记忆 → AI记忆中枢（AI-MemoryHub）
│   ├── migrate_codex_memory.py # Codex Memories → AI记忆中枢（AI-MemoryHub）
│   ├── compact.py            # 上下文压缩归档确定性落库（3 sink + 冲突 trail）
│   ├── rebuild_index.py      # 索引/目录树全量重建（EXE 的源码态）
│   └── ...                   # 以及 relocate_package / sync_skills / archive_paper 等
├── pyproject.toml                # 零运行时依赖声明
├── README.md
└── LICENSE
```

`__init__.py`（hma/、hma/engine/、hma/engine/handlers/、skills/*/）为包标记，无业务逻辑。

---

## 内容即数据：引擎固定、内容下沉

系统采用内容即数据架构：

- **内容即数据**：所有记忆素材即 `memory/` 下的 `.md` 事件包（零依赖、可手写、front-matter 即索引）。
- **引擎固定**：`hma.engine` 直读/直写 `memory/` 事件包，新增主题零代码。
- **分支接口**：`engine/registry.py` 的 `@register(mode)` 装饰器 + `dispatch(mode, doc)`。

```bash
python -m hma.engine modes         # 列出已注册 mode
python -m hma.engine query <root> <q>         # L1 确定性检索（包级，关联发现用）
python -m hma.engine query_anchors <root> <q> # L2 章节级检索（按 ## 锚点精确定位，找某轮/某节）
python -m hma.engine daylog add <一段叙事> [--linked --tags --date]  # 记当日叙事账
python -m hma.engine daylog show <日期> [--q]                    # 某天干了啥 / 包内精搜
python -m hma.engine daylog range [--start --end --q]            # 一段日子（日历序）
```

记忆直接写成 `memory/<namespace>/<id>.md` 事件包（YAML front-matter + `##` 标题树），由 `hma-ingest` 等技能或 `Memory(root).write(...)` 直写。每个包自带 `linked` 字段 → 一步到位写入 → 重复写对同一内容**真正幂等**（不产生 changes 噪声）。

已注册 mode：

| mode | 作用 |
|:---|:---|
| `packs` | 显式事件包清单，最通用（取代原 3 个 build 脚本） |
| `oc_dossier` | 结构化 dossier → 3 层铁律切片（基础包/故事包/拓展包） |
| `note` | 原始文本 → ingest 管线 |

> 设计实录另存于 `memory/项目/hma-design-journal/`。

---

## 三种用法

### 1. 命令行（人工 / 脚本）

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

### 2. MCP server（接任意 AI 客户端）

```bash
python -m hma.server --root memory
# 或 entry point： hma-mcp --root memory
```

`stdio` 上的 JSON-RPC 2.0，只实现最小子集：`initialize` / `tools/list` / `tools/call`。
暴露 7 个工具（对应三级检索漏斗 L1→L2→L3）：

| 工具 | 作用 |
|:---|:---|
| `memory_write` | 被动结构化写入一个事件包（id 存在则覆盖） |
| `memory_query` | 无状态确定性检索，返回 Top-K 候选（命中 ID，L1 包级） |
| `memory_query_anchors` | L2 章级锚点检索，按 `##` 标题精确定位某轮/某节（返回 locator） |
| `memory_read_section` | L3 取正文：按 (id, heading) 只读该 `##` 章，零冗余 |
| `memory_link` | 双向关联两个事件包 |
| `memory_rebuild` | 从 `.md` 全量重建索引（`.md` 是权威源，不丢数据） |
| **`memory_ingest`** | **主动收录：用户贴一段文本，AI 跑完整管线**（见下） |

Claude Desktop / Codex / Cline / WorkBuddy 等任何 MCP 客户端，加一段配置即可：

```json
{
  "mcpServers": {
    "hma": {
      "command": "python",
      "args": ["-m", "hma.server", "--root", "/path/to/.memory"]
    }
  }
}
```

#### WorkBuddy 即插即用部署（推荐）

WorkBuddy 用户不必手写上面的 mcp.json——仓库自带一键部署脚本：把启动器复制到 WorkBuddy 配置目录、合并写出 `~/.workbuddy/mcp.json`（只动 `hma` 连接器、保留其它连接器、托管 python 版本自动探测、不写死），并登记 `~/.hma_home` 指针：

```bash
python scripts/deploy_mcp.py            # 部署（幂等，可重跑）
python scripts/deploy_mcp.py --dry-run  # 只预览将写出的配置
```

启动器 `scripts/mcp_launch.py` 运行时读 `~/.hma_home` 指针 + 复用 `scripts/where.py` 定位 `memory/` 根，**不写死任何仓库绝对路径**；仓库搬家只需重跑一次 `deploy_mcp.py`。部署后在 WorkBuddy 连接器管理页点「信任」激活 `hma` 连接器，新窗口即出现 `mcp__hma__*` 工具。

### 3. 作为库（Python `import`）

```python
from hma.hma_core import Memory
m = Memory("memory")
m.write(id="x", title="X", summary="s", tags=["t"], body="# X\n正文")
for rid, title, summary, score in m.query("x"):
    print(rid, score)
```

---

## `memory_ingest` —— 主动收录接口

这是你要的"用户上传一段文本，AI 执行收录全流程"：

```
用户贴文本 ──▶ memory_ingest ──▶ LLM(模型无关) 理解并：
   ① 读取现有包摘要（仅索引，用于关联发现）
   ② 按 CEMA 凝聚性+体积闸门拆分为事件包（多主题就拆多包）
   ③ 为每个包生成元数据（id / title / summary / tags / aliases / body）
   ④ 写入 .md 权威源 + upsert 索引
   ⑤ 与现有 / 新建包建立双向关联
```

模型由通用适配器决定（见下），**今天 Claude、明天 GPT、后天本地 Ollama 都不用改代码**。
未配置任何 API key 时，**退化为单包启发式**，保证工具永远可用。

```bash
# 有 LLM：AI 自动拆分+关联
echo "周会：放弃 RAG，改事件驱动；下周三前完成 MCP 评审。" \
  | python -m hma.cli --root memory ingest --scope wb

# 无 LLM / 不想调模型：单包兜底
echo "随手记一条想法" | python -m hma.cli --root memory ingest --no-llm
```

---

## 零成本收录（skill 方向 / Agent 即理解层）

没有 API key 也能跑完整收录——让**当前会话的 Agent（你用的这个助手）充当理解层**，
由确定性引擎落库。这跟上面的"付费 LLM 路径"是**同构可替换**的两条客户端：

| 客户端 | 理解层由谁承担 | 何时用 |
|:---|:---|:---|
| `hma-ingest` 技能（零成本） | 本会话 Agent | 现在、没 key、想立刻用 |
| `note` 模式 + `llm_adapter`（付费/本地） | 真实 LLM API | 配了 `OPENAI_API_KEY`+`HMA_LLM` 后 |

两条路共用同一套引擎落库，产出结构完全一致（都遵循 `hma/ingest.py:build_prompt` 规则）。

### 通用前门：加载 `hma-intake` 元路由技能
当一段文本「是什么类型都不确定」就丢过来（"这段帮我存""这篇论文归档一下"），先加载
**`hma-intake`**——它只做**理解层的分类决策**，按决策树判类型后**链式加载**对应专用技能，
自己不写任何 `memory/` 文件：

| 判定类型 | 派发到 | 落库路径 |
|:---|:---|:---|
| A：角色 / OC 档案 | `oc-dossier`（store 分支） | `原创角色/<角色>/`（基础+故事+拓展包） |
| B：用户自身数据（偏好/思路/方法论） | `hma-ingest` | `用户/<子主题>/`（主语是用户本人→入 User 命名空间，不进话题类目） |
| C：论文 / 资料 / 长文（要归档 + 理解） | `hma-ingest`（文章/资料分支） | `其他/<学科>/<主题>/`（`<主题>-orig` 原文包 + `<主题>-review` 综述包，互链） |
| D：零散文本 / 通用想法 / 笔记 | `hma-ingest` | `其他/<主题>/`（1+ 凝聚性包） |
| 项目工程（要按结构收录） | `hma-project` | `项目/<项目名>/`（需求清单/项目结构/开发日志/约定 各一 md） |

**嵌套逻辑关系（通用纪律）**：无论派发给谁，新建路径都**按内容逻辑从属嵌套**
（如尼采综述 → `其他/哲学/尼采/` 下 `<尼采原文.md>` + `<尼采综述与理解.md>`）；
引擎 `query(package_id=...)` 已支持**前缀/子孙检索**，嵌套不破坏检索。该纪律同时写进了
`hma-ingest`、`hma-intake`、`oc-dossier`、`hma-project` 等技能（双副本一致）。

### 零成本路径：加载 `hma-ingest` 技能
技能会：① 判断是否为 OC（是 → 转 `oc-dossier`）；② 用 `python -m hma.engine query`
发现现有包做关联；③ 由你（Agent）按 CEMA 凝聚性拆包；④ 直写 `memory/`（确定性 sink，不经 `sources/`）。详见技能 `references/`。

### 付费/本地路径：设环境变量即启用
`note` 模式默认退化为单包启发式；一旦设了 `HMA_LLM`（并配好对应 key/端点），就自动改走
`llm_adapter` 真实 LLM——**无需改任何代码**：

```bash
export HMA_LLM=openai          # 或 anthropic
export OPENAI_API_KEY=sk-...
python -m hma.cli --root memory ingest --scope other "一段文本"   # note 模式里的 run_ingest 自动用 LLM 拆包，直写 memory/
```

> 若 LLM 调用失败（key 无效 / 断网），`run_ingest` 会**自动退回启发式**，工具永远可用。

---

## 时间轴：单日记录包（daylog）

主记忆库按**主题而非时间线**组织，话题归并进主题包后，"那一天碰过哪些
话题"的线索会丢失。`daylog` 补上这条**正交的时间轴**，不破坏主题组织原则：

- **单日记录包**（`daylog-YYYY-MM-DD`，落 `memory/日志/`）是一篇**叙事型**日记：
  正文按时间顺序流动（"先是…随后…最后…"），`linked` / `tags` 只作**索引侧车**
  （叙事块 + 结构化字段作索引侧车）；权威正文永远在主题包。
- **时间是过滤键，不是权重**：定位 = id 内嵌日期的确定性比较，结果按日历序排列。
  不做"越新越靠前"的新鲜度加权——无状态检索铁律不破。
- 单日包本身也是标准事件包（front-matter + 叙事段 `<!--beat-->` 侧车 + 由 tags 派生锚点），
  索引销毁可重建。

**写（收录即写）**：每次收录落库后顺手追加一段叙事——
```bash
python -m hma.engine daylog add "一段叙事：这天发生的一件事/进展" \
    --linked 主题包id --tags 关键词1,关键词2 [--date 2026-07-25]
```
叙事段用「先是 / 随后 / 最后」等连接词让一天连贯，**不要**写成关键词卡片；`--linked/--tags` 仅索引用。

**读（两种唤起）**：
```bash
python -m hma.engine daylog show 2026-07-25            # 全天模糊型：那天都干了些什么
python -m hma.engine daylog show 2026-07-25 --q 关键词  # 精准搜寻型：那天是不是做过 XXX
python -m hma.engine daylog range --start d1 --end d2   # 一段日子（可加 --q）
```
"前天 / 上周三"等模糊时间语由 Agent（理解层）解析成 ISO 日期后再调命令——
理解归 AI，定位归脚本。命中叙事段后沿 `linked` 一对一映射调主题包正文。

---

## 上下文压缩归档（昼夜节律 · Agent 即理解层）

CEMA「昼夜节律式后台整理」的**现实落地版**：
当**上下文窗口将满**时，把"已讨论完、暂未落库、但以后可能要用"的溢出内容，
由 Agent（理解层）判定落点 + 生成冷凝摘要，确定性写交 `scripts/compact.py`。

**分工**：你（Agent）只做理解——挑溢出片段、按内容选落点、
写冷凝摘要、发现前后冲突；`compact.py` 只做确定性写——拼包路径、加标签、冲突时追加 trail、刷新统一索引。

**3 个落点（Agent 按内容判）**：
- **daylog**：叙事 / 时间线内容 → 追加进 `memory/日志/daylog-YYYY-MM-DD.md`（叙事 beat 侧车）。
- **cache**：纯溢出缓存（散碎、暂无归属主题）→ `memory/cache/archive/<eid>.md`（临时缓存包，命名空间已注册进 `tree.py`）。
- **progress**：项目相关 → `memory/项目/<project>/<eid>.md`（当前项目进度事件）。

**铁律（内容即数据）**：
- 压缩 = **加法式冷摘要**：Agent 生成的 condensed summary 写入 sink，**权威原文一字不动**（冷摘要 + 热全文两层）。
- 默认**不碰权威原文**；仅当新信息与某权威事件**真正冲突**时，才用 `--conflict-event` 覆盖该事件 body，
  并追加可审计 trail：`> 修改 @ <ISO>: <一句话简介>`（文档 L469–470）。
- 落点即写即入统一前台 `index.db`（`package_id` 由路径自动推导，无需额外 install）——`tree.py` 也会自动把 `cache/` 收进目录树。

**触发**：
- 主触发 = **Agent 窗口压力**（你判断窗口将满时主动加载 `hma-archive` 技能）。
- 另有一个**每日定时 automation（字面昼夜节律夜间窗口）已建但 PAUSED 搁着**，待想好使用场景再激活。

**用法（理解归你，写归脚本）**：
```bash
cd hma && python scripts/compact.py \
    --root memory --sink <daylog|cache|progress> \
    --summary "<冷凝摘要>" --source "<溢出来源，如 对话溢出/2026-07-25>" \
    [--date YYYY-MM-DD]            # daylog
    [--id <eid> --title "<标题>"]   # cache/progress
    [--project <pid>]            # progress（如 hma-design-journal）
    [--linked a,b] [--tags x,y]
    [--conflict-event <id> --conflict-intro "<一句话>"]   # 仅真冲突
```
技能 `hma-archive`（双副本 user `~/.workbuddy/skills/` + 项目 `hma/skills/`，随开源）
是此入口的即插即用客户端——加载即按上面流程跑，确定性写全交 `compact.py`。

---

## 导入外部开发日志作为事件包

`daylog` 是**时间索引层**（一天一包、不收正文）。当要把**详尽内容**也收进来时，
可把外部按「第N轮 / Round N」组织的项目工作日志，全量迁移为 AI记忆中枢 的 `hma-design-journal` 包内的
**项目开发日志**事件文件——给外部开发日志装上 CEMA 前台索引（可检索、可链接、按需取正文）。

- **事件文件**：`dev`（id），落 `memory/项目/hma-design-journal/`，归入 `hma-design-journal` 包（`scripts/migrate_wb_memory.py` 生成）。
- **全量原文灌入**：外部工作日志的 `## 话题` + `### 第N轮 / Round N` + 要点**逐字保留**，
  仅确定性重排标题层级——检索主轴 `第N轮 / Round N` **提升为 `##`**
  （`anchor_derive` 只扫 `##`，故不改派生器；中文数字`第三轮`与阿拉伯/`Round N` 都算轮次）。
- **时间是 WHERE 过滤键**：写进每段 `(日期)` 后缀 + `> 来源` 指向原文件，非排序权重，无状态检索铁律不破。
- **归入既有包、不另立包**：`dev` 直接作为事件归入 `hma-design-journal` 包（时间视角），与其主题事件互补；因同包，无跨包 linked 自链（linked=[]）。

**迁移（确定性，零 LLM 依赖）**：
```bash
python scripts/migrate_wb_memory.py \
    --wb-dir "/项目/.workbuddy/memory" \
    --root memory/项目/hma-design-journal --id dev \
    --title "项目开发日志"
```
（范围仅 `2026-*.md` 每日工作日志，排除 MEMORY/README/proj-* 等非日志文件；
理解层只做"定位外部工作日志源 + 确认归入 hma-design-journal 包"，重排与落库全交脚本。）

**检索（三级漏斗完整可用）**：
```bash
python -m hma.engine query         memory/项目/hma-design-journal "项目开发日志"   # L1 包级
python -m hma.engine query_anchors memory/项目/hma-design-journal "第三轮"       # L2 章节级：找某轮干啥
python -m hma.engine query_anchors memory/项目/hma-design-journal "Round 27"     # 中文/阿拉伯/英文轮次都命中
python -m hma.engine read_section  dev "第三轮：…"  # L3 取整章正文
```
（注：`query` L1 只搜包级 id/title/summary/alias/tag；**找某轮/某节的具体内容走 L2 `query_anchors`**——
这正是文档三级漏斗 L1→L2→L3 的分工。）

技能 **`memory-import`**（双副本 user `~/.workbuddy/skills/` + 项目 `hma/skills/`，随开源）
固化此流程 = 又一个 skill 即插即用客户端。现已**通用化**为「客户端原生记忆 → AI记忆中枢（AI-MemoryHub）」路由器：
默认支持 WorkBuddy（`.workbuddy/memory/2026-*.md` → `scripts/migrate_wb_memory.py`）与 Claude Code
（`~/.claude/projects/<hash>/memory/` AutoMemory → `scripts/migrate_claude_memory.py`），其他客户端按同构适配器扩展。

---

## 通用大模型适配器（模型无关）

`hma/llm_adapter.py` 把不同厂商 API 收敛成一个统一接口：

```python
from hma.llm_adapter import get_adapter
llm = get_adapter(provider="openai")          # 或 "anthropic"
resp = llm.chat([{"role":"user","content":"..."}])
print(llm.content_text(resp))
```

已内置：

- **`OpenAICompatibleAdapter`** —— OpenAI、Groq、Together、DeepSeek、Moonshot、
  Ollama(openai 兼容)、vLLM、LM Studio……凡 `/chat/completions` 兼容皆行
- **`AnthropicAdapter`** —— Claude 官方 API

通过环境变量配置，零代码改动：

```bash
# OpenAI 系
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com/v1   # 兼容端点可改
export OPENAI_MODEL=gpt-4o-mini

# Anthropic
export ANTHROPIC_API_KEY=...
export ANTHROPIC_MODEL=claude-sonnet-4-20250514

# 让 HMA 默认用哪套
export HMA_LLM=openai        # 或 anthropic
```

`-- 一个接任意模型的"会记忆的对话 agent"最小循环。

---

## 设计不变量

| # | 不变量 | 保证 |
|:---|:---|:---|
| A | Agent 直写，无夜间流水线 | 设计内建（无夜间流水线） |
| B | 启动注入有界（只注相关，非整体膨胀） | 设计内建（注入有界） |
| C | 按需取冷正文（检索不碰正文） | `memory_query` / `show` |
| D | 关联单源（front-matter，无裂脑） | front-matter 单源写入 |
| E | `.md` 是权威源，删索引可重建 | index.db 可由 .md front-matter 全量重建 |
| F | 琐碎降权（静态，非新鲜度/热度） | 静态降权策略 |

---

## 召回颗粒度与锚点派生

检索漏斗分三级：L1 `query`（定位包，~22 字摘要）→ L2 `query_anchors`（定位子事件，返回 locator）→ L3 `read_section(id, heading)`（只读该 `##` 段）。实测以 veronica-origin（28542 字）样本，漏斗 payload 4831 字 → 较 origin 包省 83.1%、较整库 35503 字省 86.4%。

**召回单元锁定为 `##` 叙事自洽单元（章）**：不下降到 `###` 节拍级、不缝合 recap-chain。原因：`##` 是作者有意的语义边界（自洽前因后果），对任意 OC 零写作风格依赖；`###` 节拍级优化会过度拟合单一样本（反例：luzhao 的 `###` 首句是叙事描写、nerein 无 `###`）。`##` 粒度下约 80% 节省是诚实下限，绝不牺牲连贯。跨章因果伏笔属 AI 讲述时的判断，不靠切片解决。

**锚点自动派生器（已实现）**：`hma/engine/anchor_derive.py` 的 `derive_anchors(text)` 扫描 `##` 标题树（**不**下降到 `###`）→ 生成章级锚点（`title`/`locator` = 标题原文、`summary` = 章首句、可全量重建）。仅定位「哪一章」，不切分；确定性、OC 无关、不依赖 LLM。

- **构建时自动派生**：`packs` handler 在包未显式给 `anchors` 时，从正文 `##` 树自动派生（手写锚点如 veronica 的 8 个保留不动）。
- **命令式回填**：`python -m hma.engine derive <root>` 对已落库记忆重派生并写回（`root` 须直接含事件 .md）；**幂等**——再派生与正文一致则跳过、不产 changes 噪声。

---

## 从其他 AI 客户端迁移记忆

`scripts/` 下的 `migrate_wb_memory.py` / `migrate_claude_memory.py` / `migrate_gemini_memory.py` / `migrate_codex_memory.py` 
把各 AI 客户端的原生长期记忆迁移进 AI记忆中枢（AI-MemoryHub），给它们装上可检索的 CEMA 前台索引。

```bash
# WorkBuddy
python scripts/migrate_wb_memory.py --wb-dir ".workbuddy/memory" --root memory/项目/hma-design-journal

# Claude Code
python scripts/migrate_claude_memory.py --root memory --namespace 其他

# Gemini CLI
python scripts/migrate_gemini_memory.py --root memory --namespace 其他

# Codex
python scripts/migrate_codex_memory.py --root memory --namespace 其他
```

详见 `memory-import` 技能文档。

> 迁移哲学：遵循 CEMA「拆分由凝聚性+体积触发，不提前拆小东西」——
> 稳定知识合并/提升，流水账收进降权日记包。

---

## 安装 / 发布

```bash
pip install -e .          # 提供 hma-mcp / hma 两个命令
```

`pyproject.toml` 声明**零运行时依赖**（仅标准库）。

## 当前状态

**定位**：未妥协版参考实现 + 个人哲学试验场——把事件化记忆、前后台分离、不遗忘等设计在零依赖下做了工程验证，停在"前沿记忆系统在 Transformer 架构约束下妥协前的那一步"。

**已兑现的哲学**：

- 事件化记忆（事件为唯一载体，不按短期/长期、情景/语义分类）
- 前后台严格分离（薄 SQLite 索引 + Markdown 正文，索引可由 front-matter 全量重建）
- 不遗忘、全保留（无重要性评分、无遗忘曲线，判断留给检索时）
- 反向量猜测的交互澄清（降级版：query 返回 Top-K 候选 + 建议反问提示，由用户决定是否反问）
- Tag 即 Mod 的包级装卸（复制/删除 memory 下文件夹 = 装卸一块认知）
- 跨窗口离线整合（昼夜节律设计：开新对话窗口专做整合，不挤实时路径）

**工程状态**：

- 零第三方运行时依赖（仅 Python 标准库）
- MCP server 暴露 7 工具（write / query / query_anchors / read_section / link / rebuild / ingest）
- 技能作为即插即用客户端（hma-ingest / hma-intake / hma-project / oc-dossier / memory-import / hma-archive）+ 常驻主动触发技能（hma-always / hma-launch）
- 引擎固定、内容下沉（`memory/` 为单一权威存储，新增主题零代码）
- 三级检索漏斗 L1→L2→L3（包级 → 章节级 → 正文段）

**留作占位、未兑现**：

- 窗口内实时活文档整合重置（边对话边把碎片整合进既有正文、重置为最新综述）——在当前 Transformer 架构下做不出完整版（对话上下文膨胀 + TF 无持久状态），留待非 TF 架构（有持久状态的 SSM/Mamba 类，或真 AGI）

**未验证项**：

- 真实数据闭环：ingest→query 端到端尚未在真实使用中跑通
- MCP 连接器需在客户端点「信任」激活

> 本项目作为参考实现定格，不再继续开发。

## License

MIT
