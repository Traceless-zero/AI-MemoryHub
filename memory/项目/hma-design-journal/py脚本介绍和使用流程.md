---
id: py脚本介绍和使用流程
title: py 脚本介绍和使用流程
summary: HMA 的引擎 CLI 与 scripts/ 下独立确定性脚本的职责与调用方式
aliases: [ script, 脚本, py脚本, 脚本介绍, 脚本使用 ]
tags: [ hma, script, overview, 使用流程 ]
linked: [ 什么是HMA架构, SKILL介绍和使用流程 ]
anchors: [{"title": "引擎 CLI（python -m hma.cli）", "locator": "引擎 CLI（python -m hma.cli）", "summary": "hma.engine 包对应 MCP 工具接口，是所有读写检索的统一入口", "tags": []}, {"title": "scripts/ 独立确定性脚本", "locator": "scripts/ 独立确定性脚本", "summary": "手改 memory/ 后无需上述细节：直接双击 一键更新记忆索引.exe 即可（见下）", "tags": []}, {"title": "一键更新记忆索引.exe", "locator": "一键更新记忆索引.exe", "summary": "位置：hma/一键更新记忆索引.exe（与 memory/ 同级），单文件 ~11MB，双击即用、零依赖", "tags": []}, {"title": "调用约定", "locator": "调用约定", "summary": "确定性脚本永远不吃 token：AI 只做理解（归类/拆分/关联判断），落库、建索引、装卸、重建索引一律交脚本", "tags": []}]
created: 2026-07-26
updated: 2026-07-26
---

# py 脚本介绍和使用流程

> HMA 的脚本层是「确定性操作」的承载者——落库、建索引、装卸、重建索引全在这里，**永远不吃 token**。
> 与技能层的关系：skill 定义「AI 如何理解+路由」，脚本定义「确定性动作怎么执行」。

## 引擎 CLI（python -m hma.cli）

`hma.engine` 包对应 MCP 工具接口，是所有读写检索的统一入口。`--root` 指定「某个包目录」（如 `memory/原创角色/luzhao`）；全局检索用仓库根 `memory`。

```bash
# 写/改一个事件包
python -m hma.cli --root <包目录> write --id X --title T --summary S \
      --tags a,b --aliases "x,y" --linked A,B --body "..."

# 确定性检索（L1）
python -m hma.cli --root <包目录> query "<关键词>" --top-k 5
# L2 章级锚点（找某轮/某章节）
python -m hma.cli --root <包目录> query_anchors "<锚点关键词>"
# L3 取正文某章
python -m hma.cli --root <包目录> read_section <id> "<章节标题>"
# 双向关联两个事件包
python -m hma.cli --root <包目录> link A B
# 单包重建索引（清本 package_id 行后重扫）
python -m hma.cli --root <包目录> rebuild
# 打印 / 列出
python -m hma.cli --root <包目录> show <id>
python -m hma.cli --root <包目录> list
# AI 主动收录（粘贴文本，AI 拆分+写入+关联；--no-llm 跳过 LLM 用启发式）
python -m hma.cli --root <包目录> ingest "<文本>"
```

## scripts/ 独立确定性脚本

| 脚本 | 职责 | 调用 |
|---|---|---|
| `relocate_package.py` | 归类纠错：整包搬迁 `relocate()` / `--merge` 合并进已存在包（移文件+索引重挂+清空目录） | `python scripts/relocate_package.py <src> <dst> [--merge]` |
| `sync_skills.py` | 技能双副本同步：`diff`(只读校验) / `push`(用户级→项目级镜像) / `new`(双副本建骨架) | `python scripts/sync_skills.py push` |
| `rebuild_index.py` | 确定性重建索引（`Memory.rebuild_all()` + `tree.build_tree()`）；EXE 的源码态 | `python scripts/rebuild_index.py [<memory根>]` |
| `oc_registry.py` | OC 名字→基础包 确定性解析（实时扫 `memory/原创角色/`，无快照） | `python scripts/oc_registry.py find "<原话>"` / `list` |
| `pdf_reflow.py` | 论文 PDF 归档确定性重排（坐标恢复视觉顺序/剥页码页眉/粗体+编号判标题） | `python scripts/pdf_reflow.py <pdf>` |
| `compact.py` | 上下文压缩归档（hma-archive 调用） | 由 skill 调 |
| `archive_paper.py` | 论文/资料归档落地 | 由 `hma-ingest`（文章/资料分支）调 |
| `migrate_claude_memory.py` | 导入 Claude Code 原生记忆 | 由 `memory-import` 调 |
| `migrate_codex_memory.py` | 导入 Codex 原生记忆 | 由 `memory-import` 调 |
| `migrate_gemini_memory.py` | 导入 Gemini CLI 原生记忆 | 由 `memory-import` 调 |
| `migrate_wb_memory.py` | 导入 WorkBuddy 原生记忆（含 WB 项目级 `2026-*.md` 全量灌入 HDJ `dev`） | 由 `memory-import` 调 |
| `build_user_package.py` | 用户数据包构建 | 按需 |

> 手改 `memory/` 后无需上述细节：直接双击 `一键更新记忆索引.exe` 即可（见下）。

## 一键更新记忆索引.exe

- **位置**：`hma/一键更新记忆索引.exe`（与 `memory/` 同级），单文件 ~11MB，双击即用、零依赖。
- **做什么**：纯确定性重建——① 全量扫 `memory/` 下所有 `.md` 的 front-matter 重建 `index.db`；② 重生成 `目录结构树.md`。全程**零 AI、可随时重跑**（幂等）。
- **何时用**：
  - 手动路线：你随手改 `memory/` 里的 `.md` 后，双击一下收敛索引；
  - AI 路线收尾：任何 AI 写操作后，由 `hma-always`「收尾纪律」统一调它（或等效 `python scripts/rebuild_index.py`），与手动双击**同源**。
- **日志兜底**：无显示器/异常时写 `hma/last_rebuild.log`；设 `HMA_NO_GUI=1` 强跳弹窗（调试/无头环境）。

## 调用约定

- **确定性脚本永远不吃 token**：AI 只做理解（归类/拆分/关联判断），落库、建索引、装卸、重建索引一律交脚本。
- **路径自解析**：`rebuild_index.py` / EXE 自动定位自身同级的 `memory/`；其余脚本用 `--root` 或参数指定包目录。
- **可重建信仰**：`index.db` 是派生缓存，任何脚本（尤其 `rebuild_index.py`）都能由 `.md` 全量重建，索引丢了不慌。

> 相关：技能层总览见 `SKILL介绍和使用流程`；架构总览见 `什么是HMA架构`。
