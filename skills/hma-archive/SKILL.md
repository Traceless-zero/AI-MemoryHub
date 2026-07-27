---
name: hma-archive
description: >
  当上下文窗口将要用完、或用户说"归档一下""压缩记忆""上下文要满了""整理一下溢出"时，把当前溢出/暂存的内容压缩归档进 HMA。本技能是「Agent 即理解层」的上下文压缩归档入口（昼夜节律的现实落地版，q-0 合规）：AI 判定落点 + 生成冷摘要，确定性写交给 scripts/compact.py。何时用（命中即加载）：
  - 关键词：归档、压缩记忆、上下文要满了、整理溢出、收一下、清理上下文、窗口压力
  - 口语化：「这段先存一下别占着窗口」「对话太长了，把前面的归档掉」「上下文快满了，整理一下」
  - 凡你（Agent）判断当前上下文窗口将要用完、需要把已讨论但暂未落库的内容卸到长期记忆时
---

# HMA Archive（上下文压缩归档 · Agent 即理解层）

## Overview
把**溢出/暂存的上下文**卸到 HMA 长期记忆，给活跃窗口腾地方。这是 CEMA「昼夜节律式后台整理」的现实落地版（q-0 重定）：触发不是"夜间/每日"，而是 **Agent 判定上下文窗口将满**时主动跑（外加一个每日定时 automation 作字面夜间窗口，但先 PAUSED 搁着）。

分工（严格对齐 CEMA §八原则2 / R34）：**你（Agent）只做理解**——判定哪些溢出内容要归档、按内容选落点、生成冷凝摘要、发现前后冲突；**scripts/compact.py 只做确定性写**。无需任何 API key，零成本。

## 何时加载
- 你判断上下文窗口将满（对话很长、前面讨论过但还没落库的内容很多）→ 主动加载本技能。
- 用户说"归档 / 压缩 / 清理上下文 / 整理溢出"类请求。
- 注意：若是"把一段**新**文本存进记忆"（非溢出清理），走 `hma-ingest`；本技能专管"已发生讨论的溢出内容 → 卸到长期记忆"。

## 归档流程（理解归你，写归脚本）
1. **收集溢出内容**：把当前窗口里"已讨论完、暂未落库、但以后可能要用"的片段挑出来（不要一股脑全倒，挑真正值得长期留的）。
2. **逐条判定落点（理解层，按 q-0 优先级）**：
   - 叙事 / 时间线内容（"我们先做了 X，随后 Y"）→ **daylog**（时间轴索引层，`daylog-YYYY-MM-DD.md` 叙事 beat）
   - 纯溢出缓存（散碎、暂无归属主题）→ **cache**（`memory/cache/archive/<eid>.md` 临时缓存包）
   - 项目相关（明显属于某个进行中项目）→ **progress**（当前项目包内的进度事件，如 `Project/hma-design-journal` 的进度事件）
3. **生成冷凝摘要（理解层）**：为每条写一句话 condensed summary（≤30 字最好），作为写进 sink 的正文。这是"加法式冷摘要"——**原权威正文一字不动**，摘要只是新落到 sink 的衍生视图（冷摘要 + 热全文，R27–29 分形）。
4. **发现前后冲突**：用 `query` 扫现有包，若某条新信息**与某权威事件矛盾**，记下该事件 `id` + 一句"改了什么"的简介（用于 trail）。默认**不碰权威原文**——只有真冲突才覆盖。
5. **确定性写（调 compact.py）**：每条按落点调 `scripts/compact.py`：
   ```bash
   cd hma && python scripts/compact.py \
       --root memory --sink <daylog|cache|progress> \
       --summary "<冷凝摘要>" --source "<溢出来源，如 对话溢出/2026-07-25>" \
       [--date YYYY-MM-DD]            # 日志 落点
       [--id <eid> --title "<标题>"]   # cache/progress 落点
       [--project <pid>]            # progress 落点（如 hma-design-journal）
       [--linked a,b] [--tags x,y]
       [--conflict-event <id> --conflict-intro "<一句话>"]   # 仅真冲突：覆盖该事件 + 追加 trail
   ```
   - daylog：`--sink 日志 --date <今天>` → 追加一段叙事 beat。
   - cache：`--sink cache --id <稳定eid> --title "<标题>"` → 落 `memory/cache/archive/<eid>.md`。
   - progress：`--sink progress --project <pid> --id <eid> --title "<项目> 进度日志"` → 落 `memory/项目/<pid>/<eid>.md`。
   - **冲突**：加 `--conflict-event <权威事件id> --conflict-intro "<改了什么>"` → 脚本覆盖该事件 body 并追加 `> 修改 @ <ISO>: <intro>` trail（可审计，文档 L469–470）。
6. **回报**：列出每条归档到了哪个 sink（日志 日期 / cache eid / progress 项目）、是否触发了冲突覆盖 + trail。

## 纪律（铁律，不得违反）
- **内容即数据**：compact.py 只写 `memory/` 事件 `.md`；权威原文默认**一字不动**，压缩是"溢出进缓存/日志 + 加法冷摘要"，不是销毁式改写（文档原版 L107/L480 的"正文永远一篇最新综述、永不膨胀"已按 q-0 改为合规版）。
- **默认不碰权威原文；仅冲突时带 trail 覆盖**：`--conflict-event` 是唯一改权威正文的口子，且必须带 `--conflict-intro` 留审计 trail。
- **确定性归脚本、理解归你**：你只产出"落点 + 冷凝摘要 + 冲突标记"，写 / 索引 / trail 追加由 compact.py 做。
- **隐私**：敏感内容**不要落 `memory/`**；机密内容留在仓库外，库内只记一句指向（如「详见 ~/private/xxx.md」）。

## Reference
- `scripts/compact.py`：确定性落库原语（3 sink 路由 + 加法冷摘要 + 冲突 trail 覆盖）。
- 触发机制：① 本技能 = Agent 窗口压力触发（主动加载）；② 另有一个每日定时 automation（字面昼夜节律夜间窗口）已建但 **PAUSED 搁着**，待用户想好使用场景再激活。
