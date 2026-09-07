# 改动事项

倒序记录，每条对应一次提交。改了什么、为什么改、验证到什么程度。

---

## 2026-09-07

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
