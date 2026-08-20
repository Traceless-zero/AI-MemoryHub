# 事件包 .md 模板（直写 memory/，无 build 步骤）

# 复制本模板，按 SCHEMA.md §2 填好 front-matter，直接写成 `memory/<scope>/<id>.md`，
# 然后跑 `python scripts/core/rebuild_index.py --no-gui` 派生 anchors 并重建索引。
# 注意：本文件即落库成品（单一权威源），引擎从它的 front-matter 派生索引，可直接手改。
#
# ⚠️ 格式约定（详见 memory/项目/AIMH-design-journal/SCHEMA.md §2.1）：
#   列表/字典字段可 inline JSON 单行（tags/linked 用 [..]，person/location/topic/anchors 用 {} / [..]）
#   或 block 换行式（tags: 后每行 - 项；person: 后缩进 dict；anchors 每项 - Chapter/about/keywords）。
#   引擎 _parse_fm 现已正确解析 block，二者都合规。本模板给出 inline 范本供参考，亦可手写 block。

---
title: <可读标题>
summary: <2~4 句自包含真概要，不写"已废弃/已移除"等元备注>
tags: [<tag1>, <tag2>]
linked: [<现有包或同批其他包相对路径.md>]
person: [{"<规范名>": ["<别名1>", "<别名2>"]}]
event_date: "—"
location: [{"<地点>": ["<别名>"]}]
topic: [{"<主题>": ["<别名>", "<时间如2008>"]}]
#   ⚠️ 描述表达式（属性特征原子词分解）进 topic 变体 dict；斜杠式是单一变体 token：
#   topic: [{"圣保罗之焰": ["黄/橙", "蓝", "双色", "宝石", "价值连城"]}]
#   「黄/橙」含 / 是单 token（_feat_alt_match 用 f.split('/') 做 OR 匹配），切勿拆成 ["黄","橙"] 两逗号项；
#   描述表达式绝不进锚点 keywords（keyword 只放表面 token「圣保罗之焰」+ 属性词「宝石/钻石」）。
anchors:
  - Chapter: "<小节标题>"
    about: "<该节要点 gist（自然语言，供选章消歧）>"
    keywords: ["<时间>", "<地点>", "<关键事件>", "<锚定物品>", "<人物>"]
pkage_created: <YYYY-MM-DD>
pkage_updated: <YYYY-MM-DD>
---

# <标题>

<markdown 正文，原样收录，不压缩>

## <子事件 / 锚点 1 标题>
<锚点 1 正文：一段凝聚性内容>

## <子事件 / 锚点 2 标题>
<锚点 2 正文>

# 隐私写法（敏感正文不要落 memory/）
# 机密内容留在仓库外（如 ~/private/secret.md），
# 记忆里只记一句指向，例如：
#   - 详见 `~/private/secret.md`（不写入本包正文）
