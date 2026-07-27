---
id: SKILL介绍和使用流程
title: SKILL 介绍和使用流程
summary: HMA 的 10 个技能（双副本）的职责与调用流程总览
aliases: [ skill, 技能, SKILL, 技能介绍, 技能使用 ]
tags: [ hma, skill, overview, 使用流程 ]
linked: [ 什么是HMA架构, py脚本介绍和使用流程 ]
anchors: [{"title": "技能清单（10 个）", "locator": "技能清单（10 个）", "summary": "技能清单（10 个）", "tags": []}, {"title": "双副本机制", "locator": "双副本机制", "summary": "位置：用户级 ~/.workbuddy/skills/<name>/ 与 项目级 hma/skills/<name>/（随开源）", "tags": []}, {"title": "使用流程", "locator": "使用流程", "summary": "用户触发：说触发词（如「启动HMA架构」「记一下这段」「把这个角色存下来」）", "tags": []}]
created: 2026-07-26
updated: 2026-07-26
---

# SKILL 介绍和使用流程

> HMA 的技能是「可插拔客户端」：Agent（当前对话 AI）即免费理解层，skill 定义它如何把输入路由到引擎 CLI / 脚本。
> 双副本：用户级 `~/.workbuddy/skills/` 与项目级 `hma/skills/` 须 parity（用 `sync_skills.py` 同步）。

## 技能清单（8 个）

| 技能 | 组别 | 职责 | 触发信号 |
|---|---|---|---|
| `hma-always` | 常驻/路由 | HMA 记忆能力**唯一常驻入口**（原 `hma-launch` 总开关已合并）：记忆意识默认常驻，按意图路由到子技能；含「收尾纪律」与意图路由表（`references/router.md`） | 默认常驻（无需口令）/ 启动HMA架构 / 关闭记忆模式 |
| `hma-ingest` | 收录 | 通用文本/笔记/日志/文章/资料/想法 收录：含**通用 + 文章·资料（原 `paper-archive`）**两分支；末步输出「收录钩子」 | 记一下 / 存进记忆 / 归档这篇 / 读懂这篇 |
| `hma-intake` | 路由 | 通用前门/元路由：先判输入类型，再链式加载 hma-ingest / oc-dossier / memory-import | 收一下 / 归类 / 判断类型 |
| `hma-relocate` | 纠错 | 「移包 / 合并」关键字 → 确定性调 `relocate_package.py`（整包搬迁 / `--merge` 合并）；只搬家不重造 | 移包 / 合并 / 改归类 |
| `hma-archive` | 归档 | 上下文将满时的压缩归档入口：AI 判定落点 + 生成冷摘要 → `compact.py` 确定性写 | 归档一下 / 压缩记忆 / 上下文要满了 |
| `oc-dossier` | OC 档案 | OC 存+唤醒一体：store（先跑 `oc_classify.py` 拿 verdict，structured→`dossier_build.py`、ambiguous→AI 按三层铁律拆包）+ wake（叫到已登记 OC 名字→`oc_registry.py` 解析基础包→扮演） | 把这个角色存下来 / 叫某 OC 名字并对其说话 |
| `hma-project` | 收录 | 项目工程收录：README 式功能拆包（需求清单/项目结构/开发日志/约定 各一 md，结构不装铁律） | 把项目收进记忆 / 按项目结构拆包 |
| `memory-import` | 导入 | 把 AI 客户端原生记忆（WB/Claude Code/Gemini/Codex）迁移进 HMA，装上 CEMA 前台索引 | 把 XX 记忆收进 HMA / 导入 XX 工作日志 |

## 双副本机制

- 位置：用户级 `~/.workbuddy/skills/<name>/` 与 项目级 `hma/skills/<name>/`（随开源）。
- 同步：AI **只在用户级**改一份 SKILL.md，然后跑一行命令镜像到项目级：
  ```bash
  python scripts/sync_skills.py push     # 用户级 -> 项目级 整目录镜像
  python scripts/sync_skills.py diff     # 只读校验双副本 parity
  python scripts/sync_skills.py new <名> [描述]   # 两侧各建最小骨架
  ```
- 纪律：确定性镜像归脚本，AI 不手改两副本（省 token，契合 HMA 铁律）。

## 使用流程

1. **用户触发**：说触发词（如「启动HMA架构」「记一下这段」「把这个角色存下来」）。
2. **加载 skill**：对应 SKILL.md 被加载，AI 按其中的流程执行。
3. **AI 理解 + 调引擎/脚本**：归类、拆分、关联判断归 AI；落库、建索引、装卸、迁移交给 `hma.engine` CLI 与 `scripts/` 下脚本（确定性）。
4. **收尾调 EXE**（hma-always「收尾纪律」）：任何写操作后，统一调用 `一键更新记忆索引.exe`（或 `python scripts/rebuild_index.py`）做确定性重建——刷新 `index.db` + 重生成 `目录结构树.md`，与手动双击是同一条路径。

> 检索（不写）走引擎：`python -m hma.engine query <root> "<词>"`（L1）→ `query_anchors`（L2）→ `read_section`（L3）。
> 相关：技能总览见本包；脚本总览见 `py脚本介绍和使用流程`。
