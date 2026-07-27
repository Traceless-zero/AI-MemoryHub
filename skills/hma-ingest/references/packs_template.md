# 事件包 .md 模板（直写 memory/，无 build 步骤）

# 复制本模板，按需增删 `##` 锚点，直接写成 `memory/<scope>/<id>.md`，
# 然后跑 `python scripts/rebuild_index.py --no-gui` 派生 anchors 并重建索引。
# 注意：本文件即落库成品（单一权威源），引擎从它的 front-matter 派生索引，可直接手改。

---
id: <kebab-case，全局唯一，如 user-data / demo-mdnote-reqs>
title: <可读标题>
summary: <一句话摘要（≤30 字）>
aliases: [ <别名1>, <别名2> ]       # 可选
tags: [ <tag1>, <tag2> ]            # 2–5 个
linked: [ <现有包id 或 同批其他包id> ]  # 可选；一步到位写入关联
anchors: []                          # 由引擎从 ## 自动派生，不要手填
created: <YYYY-MM-DD>               # 引擎托管，可不写
updated: <YYYY-MM-DD>               # 引擎托管，可不写
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
