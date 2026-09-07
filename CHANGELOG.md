# 改动事项

倒序记录，每条对应一次提交。改了什么、为什么改、验证到什么程度。

---

## 2026-09-07

### `b3139b6` 回归 5 个 error 全修（仅 `time_iso.py` 属项目本身入库；4 项测试脚本改动落在 `AIMH-devkit/`，不入库）

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
