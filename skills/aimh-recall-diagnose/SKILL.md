---
name: aimh-recall-diagnose
description: >
  召回失败三层诊断手册：该召回的内容没召回、明明存在却搜不到时，按
  「① FM 字段 → ② index.db → ③ 代码流程」从便宜到贵逐层定位，先查数据再怀疑代码。
  何时用（命中即加载）：召回失败、没搜到、为什么查不到、漏召回、检索不到、
  该命中没命中、regress 挂了找原因、诊断召回；铁律：先诊断后动手，改代码必须走沙箱。
---

# aimh-recall-diagnose · 召回失败三层诊断（FM → index.db → 代码流程）

> 原则：**从便宜到贵**。多数失败在前两层（内容没写对 / 没进库、库不新鲜），改代码是最后一步且必须走沙箱。
> 每条命令均已实测（仓库根执行）。定位到哪层修哪层；修完必回归。

## 第 0 步：固定最小失败用例
- 写下三件事：**查询原话 / 期望命中的包·锚点 / 实际返回**。
- 查询构造先用对形态：**主路径走理解层 AI 流**（NL → 实体词 → per-entity query → 合并排序），严禁 `query()` 整句 + 二元拆词当主路径（MEMORY.md §七）。关键词分解照法条先例：`民法典`+`32条` 两个 token——整串 `民法典32条` 是单 token 会 no match（normalize_terms 按 `[+\s]` 切分）。
- 用 `scope` 缩到目标子树再测，排除跨树干扰。

## 第一层：FM 字段（内容写对了吗）
```bash
python scripts/core/scan_fm.py            # 全库 FM 只读体检
python scripts/core/lint_memory.py --all  # 结构 + 锚点 5 维 lint
```
人工核对目标包 front-matter：
1. **知识真的落盘了吗**：`## 章节标题` 与正文俱在；没落盘先走 `aimh-ingest`，不叫召回失败。
2. **四要素漏填 = 漏召回**：person/event_date/location/topic 有内容就填（`[{规范名:[变体]}]`）；别名/代号/描述表达式**只进四要素变体 dict**、绝不进锚点 keywords；描述表达式斜杠式铁律（`黄/橙` 是含 `/` 的单变体 token）。
3. **锚点**：`about` 必须特征化——抽掉章名仍能与同包其他锚点互换 = 泛化，泛词互含 → BM25 稀释 → 目标被挤出 top5（paper_camus P08 红基线即此违规实例）；keywords 5 维（时间/地点/关键事件/锚定物品/人物）各 ≥1。
4. lint **ERROR 必须修**（对照 SCHEMA.md）；WARN 逐条人工判断（如医学域按领域口径重释五维，可接受）。

## 第二层：index.db（库对不对、新不新鲜）
```bash
python scripts/core/peek_index.py   # 直接瞄索引（行数 + 列）
python - <<'EOF'
import sqlite3, json, os, sys
sys.path.insert(0, '.')
from hma.hma_core import EventPackage
cx = sqlite3.connect(r'file:memory/index.db?mode=ro', uri=True)
for fp, anc in cx.execute("SELECT filepath, anchors FROM events"):
    if not os.path.exists(fp):
        print("孤儿行（文件已删）:", fp); continue
    fm = len(EventPackage.from_markdown_fm_only(open(fp, encoding='utf-8').read(), fp).anchors or [])
    idx = len(json.loads(anc or '[]'))
    if isinstance(fm, int) and fm != idx:
        print("锚点数不一致:", fp, f"FM={fm} index={idx}")
EOF
```
判读（含真实案例）：
- **包不在索引里** → 落 .md 后没 rebuild（最高频事故）→ `python scripts/core/rebuild_index.py --no-gui`，即愈。
- **孤儿行**（索引指向已删文件，如 _regress_gate 残留）→ 测试污染 → rebuild 顺带清除；若反复出现，修测试的清理逻辑。
- **FM 与 index 锚点数不一致** → FM 无锚点的文件（如 daylog）走 derive 兜底 / 索引陈旧 → rebuild；**rebuild 后仍不一致 = 引擎 bug**，进第三层（历史案例：derive_anchors 循环内 return 致单锚点）。
- 复查：`python -m hma.engine query memory "<关键词>"`（L1）确认索引有料，再 `Memory.read_section`（L3）看正文片段。

## 第三层：代码流程（召回逻辑本身）
前两层干净仍失败才轮到代码。**先沙箱，严禁同轮改生产**（MEMORY.md §七）；沙箱先例：`scripts/tests/sandbox_anchor_tier_b.py` 的 `MemorySandbox(Memory)` 子类模式（覆写 `_score`/`resolve_two_layer`，读真实 index.db，不落生产；13/13 绿）。
按打分管线自上而下：
1. **分词/归一**：打印 `normalize_terms(q)` 看切分产物（`+`/空白切分；中文无分隔整句单 token）。
2. **L1 打分与裁切**：`_score` 分数是否达线；`waterfall_cut` 相邻分差 > 75 单向裁切——gold 掉队即记录（历史案例：OR-fail-safe 把 gold 挤出 top5，law_demo 回归锁的由来）。
3. **gate 层**：coverage gate 需 ≥2 候选才启动，候选被上游饿死则 gate 永不触发（「纯净蓝+钻石」案例）；拒答四闸逐个看 `reason` 字段（`_abstain` / `corpus_missing_entity` / read_section auto_abstain / 多子问拒答）。
4. **rerank 装置**：包级 BM25 默认关（`rerank=False`）；要重开必须先改成锚点级，否则与 dK 裁切打架（MEMORY.md §九）。
5. **对照历史病**：先跑 14 项 regress（`scripts/tests/regress_*.py`）看是不是旧病复发——law_demo / coverage_gate / paper_camus P08 known_gap 都锁着各自的失败模式。
**修复纪律**：沙箱验证 → 展示结果 → **暂停等用户确认** → 才回归生产；修复后新失败模式沉淀为 regress 用例；known_gap 红基线**不得改断言洗绿**。

## 修复后必做
- 改了 FM/记忆 → `rebuild_index.py --no-gui`；改了代码 → 14 项 regress 全绿且 P07/P08 红基线保持原样。
- 记 daylog beat（案例 + 根因 + 修法）；**全新失败模式 → 回来更新本手册补一行**，让手册随病灶生长。
