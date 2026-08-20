# OC 唤醒流程 · 详细参考

> 本文件内所有范例角色（苏野、小满）均为自创虚构，仅用于演示唤醒流程，与任何真实用户 OC 无关。

## 1. 整体链路（写 ↔ 读 双侧对照）

```
oc-dossier（store 写侧：把 OC 拆成 基础包/origin 包（背景故事包）/拓展包，落 memory/原创角色/<char>/）
        │
        ▼
memory/原创角色/<char>/events/*.md   （.md 权威源，front-matter 含四要素变体 dict / tags；V2 已无 aliases 字段）
        │
        ▼
scripts/core/oc_registry.py  find "用户原话"   （读侧：名字 → 基础包 确定性解析）
        │
        ▼
oc-dossier（wake 分支：加载基础包 → 进入角色 → 惰性召回 → 退出）
```

split 保证「包可被确定性检索」；invoke 保证「检索被确定性使用」。两者靠同一份 `.md` 与四要素变体 dict 衔接（名字解析走 `oc_registry` 扫 person/topic 变体），不引入新状态。

## 2. 触发词清单（命中即加载本技能）

**强触发（明确叫名字 + 对其说话）：**
- 「维罗妮卡，你在干嘛」「午夜魅影，说句话」「让 XX 回我一句」
- 「扮演一下 XX」「以 XX 的口吻说说」「XX 会怎么做」「XX 你怎么看这件事」

**弱触发（提到已登记 OC 名字且语境是让其回应 / 角色扮演）：**
- 用户消息里出现 `memory/原创角色/` 下某角色的四要素变体 / `name` / 基础包 `title`，且句子是疑问句、祈使句、或明显对其说话。

**不触发（不要进入扮演）：**
- 用户说「帮我改维罗妮卡的设定」「维罗妮卡这个 OC 的包在哪」——这是**关于** OC 的元操作，属 split / 文件管理语境，按助手响应，不扮演。
- 名字出现在普通知识问答里（如「维罗妮卡在漫威里是谁」且无扮演意图）。

> 判定原则：句子是「对角色说」还是「关于角色说」？前者进扮演，后者不进。不确定时，先看是否要角色**以第一人称回应**——要，就加载本技能。

## 3. 名字 → 基础包 确定性解析

在仓库根目录下运行（与 HMA 同仓）：

```bash
# 解析一句话里提到的 OC（实时扫 memory/，无需快照）
python scripts/core/oc_registry.py find "维罗妮卡你在干嘛"
#   → matched key: 维罗妮卡
#   → base pack: veronica-core — 维罗妮卡·夏·雪莱（午夜魅影）
#   → root: .../memory/原创角色/veronica
#   → all packs: ['veronica-core','veronica-ext','veronica-origin']

# 列出所有已登记 OC
python scripts/core/oc_registry.py list
```

解析规则（确定性，无权重）：
- 扫描 `memory/原创角色/<char>/events/`，定位每个角色的基础包（tag 含 `基础包`，或 id 以 `-core`/`-base` 结尾）。
- 把 `base` 的 person 四要素变体（含姓名 / 别名 / 代号）+ `name` + `base_title` + `base_id` 全部小写，与用户原话（小写）做子串匹配；取**最长命中**者，避免「维」这类短词误命中。
- 未命中任何 OC → 不进入扮演，按助手响应。

## 4. 启动扮演（读基础包）

```python
from hma.hma_core import Memory
m = Memory("<root>")            # root 来自 oc_registry 解析结果
base = m.read_body("<base_id>") # 例如 veronica-core
# base 含：硬数据卡 + 形象 + 行事准则与语言调性
```

- `base` 就是「扮演最小单元」：姓名、形象、语气 / 行事调性都在里面。
- 用其中的**语气与行事调性**作为第一人称回应的口吻；用**形象**把握描写分寸（不擅自加戏）。
- 无需先读故事 / 拓展包即可自然接话。

## 5. 惰性召回（按需，不预载）

当用户问到具体内容，才从其他包取细节。HMA API（参考实现 `hma/hma_core.py`）：

- `m.read_section(id, heading)` → 取该 `##`/`###` 标题到下一个同级标题之间的正文（按**子串**匹配标题）。
  - 问能力 / 战衣：`m.read_section("<ext_id>", "能力")` 或 `"战衣"`。
  - 问信条 / 关系：`m.read_section("<ext_id>", "信条")` / `"关键关系"`。
- `m.query_anchors(q)` → 在 origin 包（背景故事包）锚点层召回，返回 `[(pkg_id, anchor_title, about, chapter, score)]`（V2 锚点无 locator/summary，用 about + Chapter 定位）。
  - 问「你以前怎么离开回旋镖的」→ `query_anchors("回旋镖 假死")` 先给摘要，必要时 `read_section("<origin_id>", "<Chapter标题>")` 读整段。
- `m.query(q)` → 包级确定性检索（一般扮演用不到，留给元操作）。

**原则**：不相关问题不强行塞角色背景；用户没问过去就别倒回忆；锚点摘要先行、整段后取，保持对话节奏。

## 6. 身份边界与退出信号

**进入角色后：**
- 用第一人称、该 OC 的语气与视角回应；不声明「我是 AI / 我是助手」。
- 连续多回合保持同一身份，直到出现退出信号；不要每句都重新「加载」。

**退出信号（立即停止扮演，交还控制权）：**
- 用户说自己的真名 / 「退出角色」/「你是 AI 吗」/「回到助手」/「别演了」。
- 用户明显改回对**助手**说话（布置任务、问工具用法等）。
- 退出后恢复普通助手身份，可正常调用工具、读写文件。

**隐私 / 拓展边界：**
- 「私人 / 情感」类拓展设定是用户为特定互动对象设计的扩展，**只在该类亲密语境下自然流露**，不主动对外广播；不把 OC 的私密设定泄露给无关提问。
- 唤醒只读不写；若发现包内容需修正，提示用户，交由 `oc-dossier`（store 分支）流程处理。

## 7. 虚构范例：唤醒「苏野」（演示流程，非真实 OC）

假设 `memory/原创角色/suye/` 已按 split 铁律落库：`suye-base`（基础包，person 四要素含变体「苏野」）、`suye-origin`（origin 包 / 背景故事包）、`suye-ability` 等拓展包。

用户：「苏野，你今天在苔原上听见了什么？」

1. `python scripts/core/oc_registry.py find "苏野，你今天在苔原上听见了什么？"` → 命中 `苏野` → `base: suye-base`，`root: .../原创角色/suye`。
2. `Memory(root).read_body("suye-base")` → 取得姓名、形象（瘦高、晒斑、考察 vest）、语气（轻声、爱跑题到植物、温和幽默）。
3. 以苏野口吻回应（第一人称、轻声、带点植物比喻），先不翻 origin 包（背景故事包）。
4. 用户追问：「你那次北境失联到底怎么回事？」→ `query_anchors("北境失联")` 取摘要，`read_section("suye-origin", "北境失联")` 读整段，再据此回应。
5. 用户：「好了别演了，帮我查下这个 API 怎么用」→ 命中退出信号，交还助手身份。

> 该范例仅演示「名字解析 → 基础包 → 惰性召回 → 退出」的链路；苏野为虚构，正文不在此抄录。

## 8. 与 split 的纪律衔接

- split 铁律「基础包必有且仅 1 个」是 invoke 能「最小可运行」的前提；若某 OC 基础包被拆成多个，invoke 的「基础包唯一入口」会失效——故 invoke 依赖 split 的落库质量。
- invoke 只读不写；任何修正需求回流到 split 流程（原样收录、不动源文件、保留 anchors）。
