# OC 拆包方法 · 详细参考

> 本文件内所有范例角色（苏野、小满）均为自创虚构，仅用于演示拆包结构，与任何真实用户 OC 无关。

## 1. HMA 包目录布局
```
memory/
  原创角色/
    {character}/            ← 一个角色一个数据集（scope 套一层）
      events/
        {id}.md            ← 事件包（.md 为权威源）
      index.db              ← SQLite 薄索引（可销毁重建）
```
- `Memory(root)` 直接以 root 为目录，自动生成 `events/` + `index.db`。
- 传 `memory/原创角色/suye` 即套两层；`.md` 权威源，索引可 `rebuild()` 重建。
- 顶层 `memory/` 只放 scope 文件夹，避免淹没主路径。

## 2. Memory API 签名（参考实现位于 HMA 项目 hma/hma_core.py）
- `m = Memory(root)`
- `m.write(id, title="", summary="", tags=None, linked=None, body="", person=None, location=None, topic=None, event_date=None, anchors=None, created=None, updated=None, ...)`（真实签名见 `hma/hma_core.py`）
  - V2 字段：`person`/`topic`/`location` 传 `{规范名:[变体]}` dict（或等价 list 包裹 `[{规范名:[变体]}]`，引擎自动归一）、`event_date` 传字符串、`anchors` 传 V2 列表；`created`/`updated` 入参落盘为 front-matter 的 `pkage_created`/`pkage_updated`；`aliases`/`features` 入参会折叠进四要素 dict（V2 不鼓励独立写）。
  - `anchors`：可选 list，元素 `{Chapter, about, keywords}`（C+A+K 对象锚点，V2 唯一形态）；字段语义见 `SCHEMA.md` §2。`Chapter`=小节标题兼正文定位键，`about`=该节 gist（选章消歧），`keywords`=章级关键词数组（满足 5 维完整性契约）。
- `m.query(q, top_k)` → `[(id, title, summary, score)]`（确定性，无权重排序）
- `m.query_anchors(q)` → `[(id, anchor_title, about, chapter, score)]`（返回锚点 `about` + `Chapter` 定位键；V2 锚点无 `locator`/`tags` 字段）。
- `m.read_section(id, heading)` → 该标题到下一个同级标题之间的正文（按子串匹配）
- `m.read_body(id)` → 完整正文
- `m.link(a, b)` → 双向关联。**重写包时须保留 `anchors`**，否则会丢锚点（已踩坑）
- `m.rebuild()` → 从 `.md` front-matter 还原索引（含 anchors），验证 `.md` 权威源铁律

## 3. Dossier 内容模板（深度 OC 适用）
每个包正文建议结构：
- **档案卡（硬数据）**：本名、别名、性别、出生年/年龄、国籍、身高、体重、职业、隶属、状态、初次登场、饰演者
- **人生经历**：详细传记（独立成 origin 包（背景故事包），原样收录）
- **能力 / 装备**
- **参与的重大事件**：每件事的定位 + 经过
- **人物关系**

> 模板是「建议结构」，非强制填充项。极简 OC 只填基础包三项即可。

## 4. 范例 A — 深度 OC（虚构：苏野，野外植物学家）
设定（虚构，非用户 OC）：苏野是一名能「听见」苔藓低语的野外植物学家，曾参与北境苔原科考。

- `suye-base`（基础包，合并 姓名+形象+语气 三者，仅 1 个）
  - 姓名：苏野
  - 形象：瘦高、晒斑、帆布多袋考察 vest、腰间旧式植物标本铁箱
  - 语气：轻声、爱跑题到植物轶事、温和幽默，习惯用植物比喻人
- `suye-origin`（origin 包（背景故事包），苔原科考叙事**原样收录**；3 个锚点示例）
  - `北境失联` / `苔原初绽` / `归航`（锚点 `Chapter` 指向正文唯一 `##`/`###` 标题）
- `suye-ability`（拓展包：听植物低语 / 苔藓导航）
- `suye-bond`（拓展包：与导师老周、同伴阿苔的关系）
- `suye-creed`（拓展包：万物有灵，不采将枯之植）
- `suye-gear`（拓展包：旧式采集箱 / 铜制放大镜）
- 构建脚本用 `load_origin_body()` 从权威 OC 源**原样抽取**故事段，零转录误差。

## 5. 范例 B — 极简 OC（虚构：小满，茶寮灶灵）
设定（虚构，非用户 OC）：小满是一个茶寮里的灶灵，只有短短几句设定。

- 仅 **1 个基础包**（`xiaoman-base`：姓名+形象+语气），无 origin 包（小满无背景故事）、无拓展包。
  - 姓名：小满
  - 形象：小小一只、半透明、系围裙、头发像沏开的茶叶
  - 语气：欢快、话少、爱哼歌
- 证明铁律浅端：最小设定即可让 AI 基本扮演。

## 6. 锚点（V2 {Chapter, about, keywords}）约定
- `Chapter` 指向正文真实标题子串（兼定位键），不发明新标题；`about` 写该节 gist，`keywords` 写章级关键词（5 维契约）。
- 多阶段同序号标题重名时，一律用唯一关卡级 `##` 或唯一 `###`。
- `about` 写 1–2 行，供扮演时「轻量召回」先给摘要，再按需 `read_section` 读整段。

## 7. 源文件纪律
- 不修改用户 OC 源；抽取走读副本 / 构建脚本。
- 源文件草稿残留、笔误由用户手动清；AI 按「原样收录」原则照收，删除后重跑构建自动同步。

## 8. 隐私与范例纪律
- 本技能内所有范例角色均为自创虚构，演示包结构用，**不得写入任何真实用户 OC 内容**。
- 若需以真实 OC 演示，应先取得用户同意并做脱敏，或仅用结构骨架（id/锚点清单）说明，不抄录原文。
