---
name: memory-import
description: 把当前 AI 客户端自带的「原生长期记忆」迁移进 HMA，让 HMA 给它装上 CEMA 前台索引（可检索 / 可链接 / 按需取正文）。当用户说"把 XX 的记忆收进 HMA""导入 XX 的工作日志 / 记忆""用 XX 的详细记录建 HMA 包""迁移 XX memory"时加载。已支持客户端：WorkBuddy（.workbuddy/memory/2026-*.md）、Claude Code（~/.claude/projects/<hash>/memory/ AutoMemory）、Gemini CLI（~/.gemini/GEMINI.md）、Codex（~/.codex/memories/）。Cursor 的 Memories 为云端存储（C/S、按账号隔离、非本地文件），暂不适配；其余客户端按同构适配器扩展。每个适配器各自标 `-only`（wb-only / claude-only / gemini-only / codex-only），即只吃对应客户端原生记忆。
---

# memory-import —— 客户端原生记忆 → HMA（通用化路由器）

每个 AI 编码客户端都有**自己的原生记忆**：WorkBuddy 写 `.workbuddy/memory/*.md`，Claude Code 有 AutoMemory（`~/.claude/projects/<hash>/memory/`），Gemini CLI 写 `~/.gemini/GEMINI.md`，Codex 自动生成 `~/.codex/memories/`。它们存的都是**本地纯 markdown**（或附带 SQLite），但都缺 HMA 这种「可检索 / 可链接 / 按需取正文」的前台索引。
注：Cursor 的 Memories 是云端 C/S 存储、按账号隔离、非本地文件，不在本路由器的本地适配器范畴（待议）。

本技能是**通用化路由器**：AI 判断用户当前在哪个客户端，定位该客户端原生记忆，喂进 HMA 同一条「读 markdown → 确定性重排 → 写事件包」管线。理解归 AI，落库归脚本。

R49 设计翻转：废弃 `external/` 隔离命名空间，改为把原客户端记忆「拆碎、按内容归类」进 HMA 规范命名空间（User / Project / Other / …），每条带 `src:<client>` + `imported` 标签与 `> 来源:` 溯源行（落库原语见 `hma/import_common.py`）。

## 何时用（命中即加载）
- 关键词：把 XX 记忆收进 HMA、导入 XX 工作日志 / 记忆、XX 的详细记录、迁移 XX memory、客户端记忆进 HMA
- 口语化：XX 不是写得挺详细吗、它那个日志别浪费、给 HMA 加个「XX 开发日志」事件文件
- 凡用户想把"某个 AI 客户端自带的记忆"接进 HMA 长期库时

## 路由表（核心：本技能是路由器）

| 客户端 | 原生记忆位置 | 适配器脚本 |
|---|---|---|
| WorkBuddy | 项目级 `.workbuddy/memory/2026-*.md` | `scripts/migrate_wb_memory.py`（wb-only） |
| Claude Code | `~/.claude/projects/<hash>/memory/`（MEMORY.md + 主题文件 + 同级 CLAUDE.md） | `scripts/migrate_claude_memory.py`（claude-only） |
| Gemini CLI | `~/.gemini/GEMINI.md`（save_memory 追加的「## Gemini Added Memories」） | `scripts/migrate_gemini_memory.py`（gemini-only） |
| Codex | `~/.codex/memories/`（MEMORY.md + rollout_summaries/ + skills/ + memories_extensions/） | `scripts/migrate_codex_memory.py`（codex-only） |
| 其他（Cursor 等云端记忆暂不适配） | 各自原生记忆目录 | 照既有适配器同构新增 `migrate_<client>_memory.py` |

AI 先判定客户端（看 cwd 属于哪个客户端项目、或问用户），再跑对应适配器。所有适配器同构：读客户端原生 `.md` → 全量原文、按内容归类进规范命名空间（`User/` `Project/` `Other/` …）的 HMA 事件包（落库原语 `hma/import_common.write_imported` + 细粒度 `python -m hma.import_entry` CLI）→ 统一前台 db 自动接住（`package_id` = `<namespace>/<client>` 路径推出）。

## WB 适配器（wb-only，已有，成熟）
详见脚本 `scripts/migrate_wb_memory.py`：读 `.workbuddy/memory/2026-*.md` → 确定性重排（轮次→H2）→ 写 `hma-design-journal` 包事件 `dev`。设计铁律同 R38：全量原文、检索主轴=第N轮（Round 29 合规）、时间=WHERE 过滤键。

## Claude Code 适配器（claude-only，已有）
`scripts/migrate_claude_memory.py`（cwd = 仓库根）：

```bash
python scripts/migrate_claude_memory.py \
    [--projects-dir ~/.claude/projects] \
    [--root memory --namespace Other] \
    [--only memory,debugging]   # 只导指定文件名 stem，默认全导
```

- 自动发现 `~/.claude/projects/*/memory/` 下每个项目 → 落 HMA 包 `<namespace>/claude-<hash12>`（默认 `Other/claude-<hash12>`；由 AI 判定该记忆的内容归属 User/项目/Other）。
- 每个源 `.md`（`MEMORY.md`→事件 `memory`、主题文件→同名事件、同级 `CLAUDE.md`→事件 `claude`）**忠实灌入**（全量原文，不重排——Claude 内存本就干净 markdown）。
- 锚点由 `derive_anchors` 自动派生；统一前台 db 自动接住。

## Gemini CLI 适配器（gemini-only，新增）
`scripts/migrate_gemini_memory.py`（cwd = 仓库根）：

```bash
python scripts/migrate_gemini_memory.py \
    [--gemini-dir ~/.gemini] \
    [--memory-file GEMINI.md] \
    [--root memory --namespace Other] \
    [--only memory]
```

- 读全局记忆 `~/.gemini/GEMINI.md`（文件名可在 settings 改，用 `--memory-file` 覆盖）→ 落 HMA 包 `<namespace>/gemini`（默认 `Other/gemini`），事件 `memory`（`GEMINI.md`→`memory`）；由 AI 按内容归类进 User/项目/Other。
- 全量原文灌入；`## Gemini Added Memories` 等 H2 段由 `derive_anchors` 自动成锚点；统一前台 db 自动接住。
- 默认只导全局记忆文件（长期记忆层）；项目级 `./GEMINI.md` 属「项目指令」不导，避免把规则当记忆污染。

## Codex 适配器（codex-only，新增）
`scripts/migrate_codex_memory.py`（cwd = 仓库根）：

```bash
python scripts/migrate_codex_memory.py \
    [--codex-dir ~/.codex] \
    [--root memory --namespace Other] \
    [--only memory,2026-04-15-refactor-auth]
```

- 读 `~/.codex/memories/` 下全部 `.md`：根级 `MEMORY.md`→事件 `memory`；`rollout_summaries/*.md`→`rollout-<stem>`；`skills/*.md`→`skill-<stem>`；`memories_extensions/*.md`→`ext-<stem>`。→ 落 HMA 包 `<namespace>/codex`（默认 `Other/codex`；由 AI 按内容归类）。
- AGENTS.md（静态指令/类 CLAUDE.md）**不导**——那是规则不是记忆。
- 全量原文灌入；锚点自动派生；统一前台 db 自动接住。

## 细粒度拆条（按需）
批量适配器把「一个源文件 = 一个事件」整块落入同一命名空间。若某客户端记忆本身是
混杂的多主题材料（既有用户偏好、又有项目事实、又有杂项），AI 可进一步「拆碎、
按内容归类」：
1. 读客户端原生记忆，切成逻辑条目（每段 / 每个事实）。
2. 为每条判定命名空间（`User`=用户相关 / `Project`=项目相关 / `Other`=杂项资料）
   与稳定 `eid`（如 `claude-pref-py`，保证重跑幂等覆盖）。
3. 逐条调用细粒度 CLI：
   ```bash
   python -m hma.import_entry --root memory --namespace User --client claude \
       --id claude-pref-py --title "用户偏好 Python" \
       --source "~/.claude/projects/<hash>/memory/preferences.md" \
       --body-file /tmp/chunk.md [--created 2026-07-25] [--tags "py,pref"]
   ```
   落库原语 `write_imported` 自动加 `src:<client>`+`imported` 标签、追加 `> 来源:` 行、
   派生锚点；同 client+namespace+eid 重跑幂等覆盖。

## 设计铁律（严格对齐 CEMA / HMA 不变量）
1. **全量原文灌入**：内容逐字保留，只确定性重排标题层级，不增删、不"总结改写"。
2. **AI 只理解、脚本确定性写**：本技能只做"判定客户端 + 确认归属包"，重排 / 落库 / 索引交适配器脚本。
3. **无状态检索铁律（§13）不破**：时间是 WHERE 过滤键，不是排序权重。
4. **不另立冗余包**：WB 开发日志归入既有 `Project/hma-design-journal`（事件 `dev`）；Claude / Gemini / Codex 等外部记忆按内容归类落 `<namespace>/<client>` 包（User/项目/Other，由 AI 判定），每条带 `src:<client>` + `imported` 标签与 `> 来源:` 溯源行；与 HMA 原生主题包互补，不把原文再抄一份进设计包。
5. **范围 = 仅客户端「长期记忆」类 markdown**；客户端的项目指令 / 规则文件（CLAUDE.md / AGENTS.md / 项目级 GEMINI.md）若与 HMA 现有包重叠，另行处理（不盲目复制）。
6. **内容摘要取首条非标题内容行**（适配器 `_lead_line`）：HMA 的 L1 `query()` 只匹配 id/title/summary/aliases/tags，不搜正文；若 summary 落到 markdown 标题行则几乎不可召回。故摘要取真正内容首行（如 "My preferred programming language is Python."），让 save_memory / Memories 的关键事实可被关键词命中。

## 验证（两种唤起都该命中）
```bash
# L1 包级（id/title/summary/aliases/tags 命中；正文不搜）
python -m hma.engine query memory/项目/hma-design-journal "项目开发日志"   # WB
python -m hma.engine query memory/其他/claude-<hash> "XX"            # Claude（或 User/Project）
python -m hma.engine query memory/其他/gemini "python"              # Gemini
python -m hma.engine query memory/其他/codex "pytest"               # Codex
# L2 章节级（锚点召回，H2 段）
python -m hma.engine query_anchors memory/其他/gemini "memories"
# 索引销毁重建（铁律：可重建）
rm memory/其他/gemini/index.db
python -m hma.engine derive memory/其他/gemini
```

## 纪律
- 只**读**客户端原生记忆文件（不修改它们）。落库只用对应 `scripts/migrate_*_memory.py`（或细粒度 `python -m hma.import_entry`）+ 共享原语 `hma/import_common.write_imported`；不要手写 `memory/` 事件 `.md`。
- 不手改 `memory/` 下的索引。
- 双副本：本技能存于 user 级 `~/.workbuddy/skills/` 与项目 `hma/skills/`，随开源。
- 这是**通用化**技能：新增客户端 = 加一个同构适配器脚本，不改核心管线。
