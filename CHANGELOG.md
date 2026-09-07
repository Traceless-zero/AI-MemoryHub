# 改动事项

倒序记录，每条对应一次提交。改了什么、为什么改、验证到什么程度。

---

## 2026-09-07

### S5 拆分第四步：写入线抽至 `hma/write_path.py`（hma_core 3398 → 3191 行）

- **内容**：`WriteMixin`（`write` / `_upsert` / `_write_back` / `link` / `check_write_integrity` 五方法，171 行）+ 路径护栏 `_in_tree` / `_safe_md_path`（P2-D 实现，语义归写入线，37 行）收编为 `write_path.py`（255 行）。`Memory` 改继承 `class Memory(_MechanicalLayer, WriteMixin)`——方法体逐字保留，五方法互调与跨线依赖（`self.read` / `self._conn` / `self._entity_feature_index` 等）由 MRO 运行时解析。
- **留守与延迟解析**：`_entity_key` / `_search_blob` / `derive_anchors` / `Memory` 为跨线共享名留守 hma_core，write_path 内以 `_*_late()` 运行时延迟解析（避免循环 import，共 4 个包装）；`_merge_legacy` / `EventPackage` 直接从 event_package.py 导入。
- **过程中被抓的三个搬迁陷阱**（护栏+全量当场红）：①切割脚本漏 `class WriteMixin:` 类头——五个方法被 Python 解析成 `_memory_cls_late` 的嵌套死函数，compileall 照样通过但 `ImportError`（教训：**compileall 只证语法，不证名字绑定**）；②漏 `_merge_legacy`（跨包已搬，直接 import 解决）；③漏 `re` import（`_safe_md_path` 用）。
- **验收**：`regress_write_path_guard` **8/8**（P2-D 护栏随护栏实现搬迁后行为不变）；全量回归 **24 干净 / 0 语法 / 0 失败（GREEN）**；死代码清理态（4a07457）与 S5 态解析快照 **70/70 零差异**；最终 diff **4+/211-**；沙箱端到端 写→读→link→聚合 抽查 OK。
- **豆包四线至此全部归位**：解析(fm_yaml) / 事件包(event_package) / 聚合时间(aggregate_time) / 写入(write_path)。hma_core 剩检索线 + Memory 组合体，等 S4（高风险，需用户在场）。

### 死代码清理：corpus_hit_rerank 链退役（hma_core 3547 → 3398 行，-153 行）

- **背景**：2026-09-05 #05 裁决——`_abstain` 的 corpus_hit_rerank 文件粒度重排塌缩（BM25 分被丢弃、厚单文件包内密度并列退化标题序、beat12 300.4 沉底），排序职责死刑、hit_files 信号职责保留，函数体当时"保留为注释现场"（调用包在 `if False:`，daylog 标注"建议后续评估瘦身"）。本次按用户拍板执行删除，为 S4a 搬迁减负。
- **删除**（均为无消费点代码，行为零变化）：`_body_aware_rerank`（77 行）+ 仅被它调用的 `_rep_anchor` / `_rare_anchor_hit`（58 行）+ `_abstain` 内 `if False:` 死块与 `hit_files` 计算（18 行——hit_files 在活代码中无任何消费点，Gate1 现状为 `cov < kappa` 直接拒答）。
- **连带修正一处注释漂移（红线⑦）**：`_abstain` docstring 原宣称 Gate1"语义升级为语料包含性（覆盖不足→先查语料→低置信放行）"，该语义实际已随重排废除失效——现状是 `cov < kappa` 直接拒答。docstring 改写为当前真实闸序（Gate0/GateA/GateB/Gate1/Gate2 + 放行置信度规则），并指向 design-journal 与 daylog-2026-09-05 #05。
- **保留**：`_rare_entities` / `_corpus_top_term_hit_files`（有活调用者）；`hit_files` 的"语料含实体→不拒答"信号如未来 Gate1 需做包含性放行，可从 `_corpus_top_term_hit_files` 恢复（活函数未动）。
- **验证**：compileall OK；全量回归 **24 干净 / 0 语法 / 0 失败（GREEN）**；`bench_veronica_20_5` **可答 20/20（0 误拒）+ 对抗 5/5（0 漏拒）**——拒答闸行为完好；`audit_comment_pins` 无新增 UNPINNED（G2-Q5 / Edit 7 两条人工核明细随死代码注释移除，主张钉在 daylog #05 未失）；`audit_orphans` 无新增孤儿。

### S3 拆分第三步：聚合+时间线抽至 `hma/aggregate_time.py`（hma_core 4022 → 3546 行）

- **内容**：时间解析常量区（`_MONTH_ALIASES` / `_NUM_WORDS` / `_RE_ISO` / `_RE_YEAR` / `_PART_RANGE` 等十余个词表与正则，49 行）+ `TimeHint` / `parse_time_hint` / `_is_union_query` / `_time_tiebreak`（243 行）+ `_agg_build_where` / `db_aggregate` / `time_filter` / `_time_hard_match` 与 `_AGG_COL_WHITELIST` / `_AGG_UNITS` 双白名单（181 行）收编为 `aggregate_time.py`（496 行）。`Memory.aggregate` / `Memory.filter_by_time` 薄转发留在 hma_core（方法体零改动，靠 re-export 的后端名继续工作）。
- **职责边界（docstring 钉死）**：`hma/time_iso.py` 只管【相对时间→绝对 ISO 换算】，`aggregate_time.parse_time_hint` 只管【从问句抽取时间意图 TimeHint】，防止两套时间逻辑再被混用。
- **跨线依赖**：`_scope_clause`（检索侧三处共用）留守 hma_core，aggregate_time 内 `_scope_clause_late` 运行时延迟解析（S2 的 derive_anchors 同款手法）。
- **过程中被仪器抓到的三个夹带/断链**（全量回归当场红）：① `_AGG_COL_WHITELIST` / `_AGG_UNITS` 物理位置在段 D 之前未被切走 → db_aggregate 断链，已随语义搬入；② `_anchor_heading_re` / `_anchor_sent_split` / `_anchor_table_sep` 三个锚点派生专属正则物理上夹在段 D 尾部被误带走 → derive_anchors 断链（4 个回归红），已搬回 hma_core 并修正注释-代码配对；③ 头部 import 漏 `json` / `sqlite3`，已补。
- **验收**：全量回归 **24 干净 / 0 语法 / 0 失败（GREEN）**；S2 提交态（0b7013b）与 S3 态解析产物快照 **70/70 零差异**；最终 diff **12+/487-**（行尾 CRLF 直写，无全文件改写噪音）；`from hma.hma_core import parse_time_hint, db_aggregate, …` re-export 面验证通过，`Memory.aggregate('packages')=18`、`filter_by_time('上个月')` 返回 4 包与拆分前一致。

### S2 拆分第二步：EventPackage 整类抽至 `hma/event_package.py`（hma_core 4381 → 4022 行）

- **内容**：`EventPackage` 全类（round-trip 序列化 / 写回门禁 / FM 解析别名绑定，285 行）+ 四要素兼容层三函数（`_as_four` / `_merge_legacy` / `_four_to_list`，91 行，仅被本类与 `Memory.write` 消费）收编为 `hma/event_package.py`（386 行）；`hma_core` 顶部 re-export 四个名字，外部 import 面（`hma/__init__`、`fm_schema.py`、`scripts/core/` 5 处、`lint_memory` 的 `_four_to_list`）**一行未改**。
- **过程中暴露并修掉的三个搬迁陷阱**（都是全量回归 + 快照比对当场抓的）：
  1. **类体调 `derive_anchors`（非下划线模块级函数，首轮依赖扫描的正则只扫了下划线名，漏了）** → 定义在 hma_core 尾部，搬走即断链，5 个包的解析直接 NameError。修法：`event_package._derive_anchors_late()` 运行时延迟解析，避免循环 import。
  2. **`_LOC_WORDS` / `_FIELD_W` / `_FIELD_NUDGE` / `_FIELD_CAP` 四个检索侧常量物理上夹在类体之后，被切割误带走** → `regress_law_demo` 等当场 NameError。已原样搬回 hma_core 原位置。
  3. **`__init__` 用 `date.today()` 而 `datetime` 未随迁** → 两个回归当场红。已补 import。
- **行尾卫生**：切割脚本写出 LF 而仓库内该文件为 CRLF，会制造全文件改写的垃圾 diff（4022/4381）；已转回 CRLF，最终 diff **17+/376-**，blame 可读性保住。
- **验收**：S1 提交态（cd62665）与 S2 态解析产物快照比对 **70/70 零差异**（修复三个陷阱后复测两轮）；全量回归 **24 干净 / 0 语法 / 0 失败（GREEN）**；`from hma import EventPackage` / `from hma.hma_core import EventPackage, _four_to_list` 等外部导入身份一致（`is` 同一对象）。

### S1 拆分第一步：FM/YAML 解析器抽至 `hma/fm_yaml.py`（hma_core 4567 → 4381 行）

- **内容**：按拆分计划（豆包 P2-B 落地方案）执行 S1——`EventPackage` 的 11 个解析 staticmethod（`_strip_comment` / `_scalar_or_json` / `_parse_value` / `_parse_inline` / `_is_kv` / `_empty_default` / `_parse_seq` / `_parse_mapping` / `_parse_node` / `_normalize_anchor_kws` / `_parse_fm`）与 3 个 FM 字段分类常量（`_FM_SPECIAL` / `_FM_LIST` / `_FM_DICT`）收编为 `hma/fm_yaml.py` 模块级实现（265 行，零依赖）。
- **搬法**：`EventPackage` 上保留 `staticmethod` 别名绑定（`_parse_fm = staticmethod(fm_yaml.parse_fm)` 等 11 条），**调用点零改动**——搬迁前 grep 确认 11 方法 + 3 常量仅在 hma_core 内部引用（18 处），无外部调用、无 monkey-patch 点。
- **验收**：`regress_fm_yaml` 6/6；全量回归 **24 干净 / 0 语法 / 0 失败（GREEN）**；**FM 基线快照比对 70/70 零差异**（搬迁前后对全部 70 个 `.md` 逐字比对解析产物：title/summary/tags/linked/四要素/anchors/event_date/body_sha1）。
- **新增工具**：`AIMH-devkit/tests/_fm_dump.py`（dump/diff 两命令，S2-S5 搬迁验收复用；快照含语料内容，比对完即删）。
- **性质**：纯搬迁、零行为变化；`parse_value` 的 fail-closed 语义原样随迁。

### P2-D 写侧越界修复：`memory/` 树内外隔离（护栏 1/8 → 8/8）

- **问题**：豆包审计 P2-D「防护不对称：读侧严、写侧松」。`Memory.write` / `read` 直接 `os.path.join(events_dir, f"{id}.md")`，`id` 由 MCP 入参透传。沙箱实锤 6 条越界路径全通：`../` 相对穿越、绝对路径（`join` 遇绝对路径丢弃左侧）、盘符形态、反斜杠 `..\`、读侧越界读取、树外既有 `.md` 被覆盖，且树外 filepath 会污染 index.db（`uninstall(rm=True)` 同源问题可 `rmtree` 树外目录，危害更大）。
- **改动**：
  - `hma/hma_core.py`：新增 `_in_tree` / `_safe_md_path`（归一 `\`→`/` 后按 `root+os.sep` 前缀比对，禁空/禁绝对/禁盘符/禁 `/` 开头，全 fail-closed）；`write` 落盘前、`read` 的 db-first 命中结果与 fallback、`uninstall` 删除前统一走校验。
  - `hma/server.py`：`_h_write` 补 `try/except`，`ValueError` → `(WRITE_GUARD: …) 写入被拒`（原为全文件唯一无兜底 handler）。
  - `scripts/core/new_package.py`：`path_soft_check` 拆 `(hard, soft)` 两级，绝对路径/盘符/`..`穿越归 hard 拒绝（原只有软提醒且不含 `..` 检测）。
- **两个实现要点**：①**归一不是禁反斜杠**——`list_all_in_scope` 返回 `人物\雪莱（诗人）\shelley-poet` 形态，禁 `\` 会把 68 条既有事件全判非法（`bench_aimh_internal_groups` 当场红）；②**Python 3.13 起 Windows 上 `isabs("/x")` 返回 False**，单 `/` 开头须显式补捕。
- **验证**：新增护栏 `AIMH-devkit/tests/regress_write_path_guard.py` 8 用例（红基线 1/8 → 修复后 **8/8**）；引擎边界抽查 `/evil` / UNC / `C:/x` / `../x` 全拒、正常 id 放行；既有 68 条事件 read 全恢复（0 失败）；全量回归 **24 干净 / 0 语法 / 0 失败（GREEN）**。真实库 68 条事件扫描：树外 filepath 0 条，无历史污染。
- **定性**：本地单用户工具的误操作护栏缺失（触发路径＝AI 被注入诱导或手滑拼错 id），非高危远程漏洞；防护与读侧（控制台穿越检查、db_aggregate 白名单）对齐。

### `5daed94` 回归 5 个 error 全修（仅 `time_iso.py` 属项目本身入库；4 项测试脚本改动落在 `AIMH-devkit/`，不入库）

- **`regress_aggregate.py`**：`events return_list` 断言写死 `len == n_evt`，但护栏 6 有 500 硬上限，而全仓 events 已 574 条 → 恒 FAIL。属测试自身 bug，改断言为 `min(n_evt, 500)`，护栏原样保留。17/17 → **ALL PASS**。
- **`regress_obscure_recall.py`**：`PKG` 写成 `…/demo-origin`（9/06 脱敏机械改名的残留占位，文件并不存在）→ `Memory.read` 返 None → 走「无目标包」早退分支，`scope` 为 `{}`，测试读 `scope['label']` 崩 KeyError。**澄清契约**：`obscure_recall` 的 `package_id` 是「包路径 + 事件 stem」的**复合 id**（走 `Memory.read` 定位单个 `.md`），不是纯包 id。改为 `原创角色/维罗妮卡·夏·雪莱/veronica-origin`（背景故事，含「赎回」章）→ **4/4 PASS**。
- **`regress_time_iso.py`**：`parse()` 缺「裸月份」分支，`3月份` 无相对前缀落到最后返回 None。在 `hma/time_iso.py` 补分支（③，原③④顺延为④⑤）：`N月(份)?` → 锚点年内的整月区间；可再细化 `3月5号`；**有日级细化却落不了地（如 `2月30号`）一律 None**，绝不静默退回整月。同步给 `parse_text` 扫描模式补同类正则。**生产代码改动**，35/36 → **36/36**。
- **`sandbox_anchor_tier_b.py` / `verify_resolve_two_layer_dk.py`**：各 11/13，卡在同一组脱敏占位词。从 `项目备份/AI-MemoryHub/scripts/tests/`（8/28 版）用例表按位置对齐还原：**示例地点 = 红房、示例设定 = 幽影核心**。先 grep 语料确认两词只落在维罗妮卡包内（与期望包集合一致）才改断言 → 双双 **13/13**。
- **全量结果**：**23 干净退出 / 0 语法错误 / 0 失败（GREEN）**；`regress_paper_camus` P07/P08 两条 known_gap 红基线照旧输出 `[FIXD]…保留为红基线`，**未洗绿**。

### `b0a6537` FM 解析器 fail-closed：杜绝静默丢字段

- **问题**：手写 YAML 子集解析器遇到不支持的写法不报错、不告警，静默产出错误数据。FM 是唯一权威源，错了无人能察觉。
  实测复现 5 例：流式 `topic: {…}` 丢成 `{}`、`anchors: {…}` 退化成字符串、字面多行串被截断且残留引号、双引号内 `\"` 未处理、单引号内嵌双引号未剥离。
- **改动**：`hma/hma_core.py` 的 `EventPackage._parse_value`（+18/-2）——流式 `{…}` 与引号未闭合一律 `ValueError`；支持 `\" \' \\ \n \t` 转义，`\u` / `\x` 显式报错。
- **验证**：新增护栏回归 6/6（修复前 1/6）；全量回归 18 干净 / 0 语法 / 5 失败，与修复前持平无退化；全库 70 个 `.md` 无一被引爆，`rebuild_index` 重建 68 条事件正常。
- **定性**：全库扫描确认当前**无实际损坏**，属潜在风险防护（导入外部记忆时才会中招）。

### `1671cc4` 网页控制台：目录结构树.html 更名为 index.html

- git 识别为 `R`（改名，0 行内容变化），作为控制台入口。

### `185b1cf` 脚手架与项目分离：开发套件迁出至父级 AIMH-devkit

- **原因**：此前把开发脚手架（测试脚本、runner、对账清单、外部审计报告）混进项目提交。判据——**删掉它 AIMH 还能不能正常用？能＝脚手架，不能＝项目本身**。
- **迁出**：`scripts/tests/`（22 个测试脚本）、`run_all_regress.py`、`gen_track_manifest.py`、`入库目录清单.txt`、`审计报告 HTML`、`AGENTS.md`。
- **共有路径抽为单一真相源**：新增 `AIMH-devkit/tests/_paths.py`，导出 `PROJECT_ROOT / MEMORY_DIR / CORE_DIR`；22 个脚本不再各自写三级 `dirname` 推导。
- **`.gitignore`**：删 `scripts/tests/`（目录已迁出）；删 exe 忽略行（exe 属交付物，明确入库）。
- **验证**：干净退出 18 / 0 语法 / 5 失败，与迁移前持平。

### `42ef9a7` 回归仪器修复 + 入库对账清单

- 新增 `run_all_regress.py`（compileall 门禁 + 三态汇总 + 非零退出码）、`gen_track_manifest.py`。
- 测试脚本修复：硬编码绝对路径 29 处改为推导；还原 9/06 脱敏占位词 5 个（示例角色／信物／协议／别名／事件）。
- `real_regress.py` 移入测试目录并修导入方式。

---

## 2026-09-06

- 隐私清洗收尾（98 个跟踪文件无私有语料）。
- 统一示例命名（示例角色/demo-char）——**仅作用于文档层**（`SCHEMA.md:152` 规定占位写法），数据层 `memory/` 从未改名。
- 回归仪器本地化：bench / real_regress 转本地不推送（`scripts/tests/` 自此不入库）。
