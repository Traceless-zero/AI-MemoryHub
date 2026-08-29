# aimh-ingest · 文章·资料分支（论文 / 长文资料：归档 + 理解综述）

> 本文件由 `aimh-ingest/SKILL.md` 路由进入：**论文 / 文章 / 文献 / 长文资料，意图含"归档 + 理解 / 综述 / 读懂"** 时从头跑到尾。
> 原 `paper-archive` 技能已并入本分支。核心交付物：**`<主题>-orig` 原文包 + `<主题>-review` 理解综述包**一对，同 scope 互链。
> FM 契约、落库方式、模块路由、通用纪律全部以 `aimh-ingest/SKILL.md` 为准，本文件不重复。

## 流程
1. **判定与取文**：确认是论文/资料类。文件（文本 / PDF 导出的 md / 用户贴文）由你读取；记录元信息（标题 / 作者 / 出处 / 年份 / DOI）。
   · 用户只给"主题"没给原文：先问清源文本在哪（综述不能凭空编原文）。
   · **源是 PDF → 必走确定性重排管线**（`get_text` 裸提取会让双栏顺序乱、零锚点）：
     ```bash
     python scripts/core/pdf_reflow.py <pdf> --out /tmp/<主题>-orig.md   # 试跑抽查
     python scripts/core/pdf_reflow.py <pdf> --write memory <包相对路径> <主题>-orig  # 直接落库
     ```
     管线（全确定性）：按坐标恢复视觉顺序、剥页码/页眉页脚、标标题、拼段落，最后**原样校验**（非空白字符 Counter：raw == body + removed，差一字即 abort）。
2. **定位嵌套路径（按逻辑关系）**：落到 `其他/<学科>/<主题>/`。例：尼采 → `memory/其他/哲学/尼采/`；某 ML 论文 → `memory/其他/科学/计算机/机器学习/`。主题不明 → 按你的最佳推断建路径，并在回报时给「归类开口」。引擎已支持前缀/子孙检索，嵌套不破坏检索。
3. **拆成 2 个事件包（同 scope，互链）**：
   - **`<主题>-orig`（原文包）**：`body` 原文正文（纯文本且允许入库时）；大文件 / 敏感 / 版权内容留在仓库外，包内只记一句指向（守「隐私」纪律），如「详见 ~/private/<主题>.pdf」。元信息写进 body 顶部或 `summary`（标题 / 作者 / 出处 / 年份 / DOI）。`summary` 落到关键事实首行，保证 L1 可召回。
   - **`<主题>-review`（理解综述包）**：**核心交付物**，由你（Agent）中文、结构化生成：一句话核心贡献 / 方法思路 / 关键结论 / 与已有记忆的关联（真相关才 `linked`，不编 id）/ 局限 / 可复用点。`summary` 落核心贡献一句话。
4. **落库（确定性 sink = 直写 `memory/`）**：两包都写进 `其他/<学科>/<主题>/`，再 `python scripts/core/rebuild_index.py --no-gui`。CLI `write` 旗标无法携带四要素 dict / pkage_ 时间戳；若论文包需四要素（作者作 `person`、年份作 `event_date`），按通用流程直写 .md 更完整。
5. **互链**：两包互链（`python -m hma.engine ... link <主题>-orig <主题>-review`，或 `Memory.link`），导航上"原文 ↔ 综述"一体。
6. **记当日账（daylog，叙事型）**：
   ```bash
   cd scripts/core && python daylog_append.py --title "<一句话小标题>" --linked "<主题>-orig,<主题>-review" --tags "<2-4个关键词>" --body "<一段叙事：这天归档了某论文并出了理解综述>"
   ```
7. **回报（含「归类开口」，强制）**：列出两包 id / 路径 / 关联；原文过大/敏感留在仓库外则明确说明。凡 `其他/<学科>/<主题>/` 是你推断的（非用户明示），必须带固定句式：
   > **当前归类为 `<路径A>`，如有异议可以切换为 `<路径B>`（次优候选 + 一句话理由）。**
   用户答"换"即跑确定性切换（整目录搬迁 + 索引重挂，linked 按 id 不受影响）：
   ```bash
   python scripts/core/relocate_package.py memory "<路径A>" "<路径B>"
   ```
   用户不回应 = 默认接受，不追问。

## 铁律
- **原文包 ≠ 综述包**：二者必须分开（空间换复杂性）；综述是附加值，不回写覆盖原文。
- **嵌套优先**：路径按学科→主题嵌套，不摊平（子孙检索已支撑）。
- **论文体锚点规则（最小单元）**：论文每节关键且独立，orig 包锚点用 `derive_anchors(body, max_level=6)`——`##`~`######` 全进锚点，Agent 可按小节灵活召回（`pdf_reflow.py --write` 已内置）。全仓默认即 `max_level=6`。**关键词部分整段一个锚点**（`## INDEX TERMS / 关键词` 一次唤起全部关键词）。
- **综述可检索**：`summary` 落关键事实首行，确保 L1 `query` 能命中。
- **上下文纪律（防记忆污染 / 窗口腐烂）**：写 `-review` 时，Agent 只读到「能写出靠谱综述」的体量——**绝不把全文（如 500+ 行 orig）驻留 / 重读进自己的上下文**；`-orig` 交确定性拷贝脚本（`archive_paper.py orig <pdf>` 或 `pdf_reflow.py --write`），Agent 不手抄。入库后**稳态检索严格走** `query`(L1) → `query_anchors`(L2) → `read_section`(L3)，**绝不把 `.md` 全文重读进上下文**。
