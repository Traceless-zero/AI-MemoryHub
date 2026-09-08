# -*- coding: utf-8 -*-
"""retrieval —— 检索线机械层（S4a 拆分自 hma_core）。

_MechanicalLayer：拒答与理解链路的确定性方法集合（零 ML、可测试、模型换代不漂）：
  候选生成  _corpus_top_term_hit_files / _corpus_blob_candidates / _entity_in_corpus
  重排过滤  _relevance_filter
  实体词表  _entity_vocab / _clean_entities / _rare_entities
  拒答闸    _abstain（四道闸 + 语料包含性判定，系统 faithfulness 的机械守门员）
由 hma_core.Memory 继承（与 WriteMixin 并列），方法内 self.* 依赖由 MRO 运行时解析。
_ABSTAIN_* 三常量为拒答层阈值，随迁至此；hma_core 经 re-export 供 Memory 检索方法使用。

留守 hma_core 的跨线共享名（本模块运行时延迟解析，避免循环 import）：
_flat_variants / _is_garbage_bigram（同属机械切分词法，被 normalize_terms 共用）。
"""

import json

from . import scoring_coeffs as C


def _flat_variants_late(fld):
    from . import hma_core
    return hma_core._flat_variants(fld)


def _is_garbage_bigram_late(t):
    from . import hma_core
    return hma_core._is_garbage_bigram(t)


# 拒答层默认阈值（在 Demo mini-bench / LoCoMo cat5 上离线校准，不靠拍脑袋）
ABSTAIN_KAPPA = 0.34    # Gate1：top 锚点 IDF 加权覆盖度 < 此值 → 拒答

ABSTAIN_HIGH_K = 0.67   # 覆盖度 ≥ 此值 → confidence=high，否则 low

ABSTAIN_DEFAULT_MSG = ("未查询到与查询词相关的记忆内容。请判断：是查询表述过窄/模糊"
                       "需要进一步向用户澄清，还是确无相关内容应明确告知用户。")


class _MechanicalLayer:
    """拒答 + 理解链路的确定性方法集合，由 hma_core.Memory 继承。"""


    def _coverage(self, scored, terms):
        """top_k 锚点集合对查询词的 IDF 加权覆盖度（与 _anchor_score 同字段）。

        返回 0..1：命中词 IDF 权重和 / 查询词总 IDF 权重。复用 engine 内
        ts_covidf「内容词 distinct 覆盖 × 池内 idf」思路，是架构内原生概念。
        关键：判据必须与 _anchor_score 打分看的字段**一致**——title+about+tags+body，
        否则会出现「body 命中、about 未命中」的正确锚点被误拒（Demo 实测 5/9
        过度拒答即此因）。聚合 top_k 锚点的可检索文本，查询词只要出现在任一召回
        锚点的完整文本里即计入覆盖（避免 top-1 恰为弱泛化锚点时漏判）。
        """
        blobs = []
        seen = set()
        for a in scored:
            rid = a[0]
            txt = ((a[1] or "") + " " + (a[2] or "")).lower()
            if rid not in seen:
                b = self._pkg_body(rid)
                if b:
                    txt += " " + b
                seen.add(rid)
            blobs.append(txt)
        blob = " \n ".join(blobs)
        w_total = 0.0
        w_hit = 0.0
        for t in terms:
            wt = self._idf(t)
            w_total += wt
            if t and t in blob:
                w_hit += wt
        return (w_hit / w_total) if w_total else 0.0

    def _entity_vocab(self):
        """全库四要素实体词表（person/location/topic/event_date 的规范值，小写）。"""
        c = self._conn()
        rows = c.execute(
            "SELECT person,location,topic,event_date FROM events").fetchall()
        vocab = set()
        for p, loc, top, d in rows:
            for fld in (p, loc, top):
                for v in _flat_variants_late(fld):
                    if v:
                        vocab.add(str(v).lower())
            if d:
                vocab.add(str(d).lower())
        return vocab

    @staticmethod
    def _is_cjk(ch):
        o = ord(ch)
        return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF

    @staticmethod
    def _boundary_hit(term, text_l):
        """CJK 词边界感知的子串命中：term 在 text_l 中出现，且匹配位置前/后字符
        非 CJK（即 term 是独立词、而非更长 CJK 词的子串）才计命中。

        治本修复拒答层 2 字 bigram 子串碰撞：计算⊂计算机 / 公司⊂待办 /
        世界⊂AIMH系统 / 小说⊂背景小说 这类「长词恰好含 2 字查询词」不再误判为
        语料有该实体（域外问题正常拒答）；而 误删(后接空格) / 写给(独立词) 等
        真事实词仍正常命中 → body-only 事实可被语料包含性兜底召回。

        后缀例外（2026-08-19 R1）：term 后紧跟方位/领域后缀（界/内/中/部…）时
        仍计独立命中——中文无空格，2 字真实体常出现在「宝石界/宝石内部」这类
        「词根+后缀」组合里，严格前后非 CJK 会误拒（黄蓝色的宝石→示例信物
        查询被 low_coverage 误拒的根因）。后缀集只收方位/领域后缀，不收实词
        成分（机/司），故 计算⊂计算机 类碰撞仍正确拒绝。
        """
        tl = (term or "").lower()
        if not tl or tl not in text_l:
            return False
        n = len(text_l)
        L = len(tl)
        start = 0
        while True:
            i = text_l.find(tl, start)
            if i < 0:
                return False
            before_ok = (i == 0) or (not _MechanicalLayer._is_cjk(text_l[i - 1]))
            j = i + L
            if j >= n:
                after_ok = True
            else:
                aj = text_l[j]
                # 后是方位/领域后缀 → 视为独立词（词根+后缀组合）；否则须非 CJK
                after_ok = (aj in _MechanicalLayer._SUFFIX_FREE) or (not _MechanicalLayer._is_cjk(aj))
            if before_ok and after_ok:
                return True
            start = i + 1

    # 方位/领域后缀：term+后缀 仍算独立词（宝石界/宝石内部 = 宝石+界/内 是词根+后缀组合，
    # 非子串碰撞；计算⊂计算机/公司⊂待办 的后缀是实词成分(机/司)，不在本集 → 仍判碰撞）
    _SUFFIX_FREE = set("界内外中里部上下间处区域层心端口位带")

    def _clean_entities(self, terms):
        """从查询 terms 中滤出「干净实体/概念词」：去掉含疑问·功能字的问句壳、
        跨域通用词、以及单字中文（sliding-window 噪声）。返回可用于语料包含性
        判定的实体候选列表。"""
        out = []
        for t in terms:
            if not t:
                continue
            if t in self._GENERIC_TERMS:
                continue
            if any(ch in self._FUNCTIONAL_CHARS for ch in t):
                continue
            # 中文需 >=2 字（sliding 单字噪声），或含 ASCII 字母（AIMH/LoCoMo 等）。
            if any(ord(c) > 127 for c in t) and len(t) < 2:
                continue
            out.append(t)
        return out

    def _rare_entities(self, terms, pid=None):
        """从 clean entities 中筛出「稀有特异实体」：出现在作用域文件比例 < 50%
        的词（如 四要素/CEMA/学历/泥沼）。排除全局高频词（AIMH 几乎每文件都提，
        无判别力）。供语料包含性判据与 body 重排共用。

        两段式计频（检索层无正文，正文按需打捞——设计铁律）：
          1. search_blob 列 SQL 计频（O(命中)，实测 9000 文件≈8ms）。blob 只含 FM 层
             文本（title/summary/四要素/tags/linked/锚点 C+A+K），不含正文；
          2. blob 计 0 ≠ 语料无此词（词可能只在正文）→ 对计 0 词做一次全库打捞：
             逐文件读 .md 正文计 df（一次读盘摊给全部计 0 词，57 包≈76ms），
             与 _entity_in_corpus 的打捞兜底同口径——正文词不因索引形态被误判稀有。
             锚点 about/keywords 频繁出现的词在 blob 层即高频，不受影响。列未填充
             （旧库未 rebuild，search_blob 全 NULL）时退回 body-only 逐文件读盘（旧库零回归）。
        """
        cl = self._clean_entities(terms)
        if not cl:
            return []
        c = self._conn()
        if getattr(self, "_blob_ok", False) and self._blob_populated():
            if pid:
                total = c.execute(
                    "SELECT count(*) FROM events WHERE package_id=? "
                    "OR package_id LIKE ? || '/%'",
                    (pid, pid)).fetchone()[0]
            else:
                total = c.execute("SELECT count(*) FROM events").fetchone()[0]
            if total == 0:
                return []
            freq = {}
            zero = []
            for t in cl:
                n = c.execute("SELECT count(*) FROM events WHERE search_blob LIKE ?",
                              ("%" + str(t).lower() + "%",)).fetchone()[0]
                freq[t] = n
                if n == 0:
                    zero.append(t)
            if zero:
                zdf = {str(t).lower(): 0 for t in zero}
                for fp in self._corpus_files(pid):
                    b = self.read_body(fp)
                    if not b:
                        continue
                    bl = b.lower()
                    for tl, cnt in zdf.items():
                        if tl in bl:
                            zdf[tl] = cnt + 1
                for t in zero:
                    freq[t] = max(freq[t], zdf[str(t).lower()])
            out = []
            for t in cl:
                r = freq[t] / total
                if r >= 0.5:
                    continue
                if len(t) <= 2 and r > 0.08:
                    continue
                out.append(t)
            return out
        files = self._corpus_files(pid)
        total = len(files)
        if total == 0:
            return []
        df = {t: 0 for t in cl}
        for fp in files:
            b = self.read_body(fp)
            if not b:
                continue
            bl = b.lower()
            for t in cl:
                if t.lower() in bl:
                    df[t] += 1
        out = []
        for t in cl:
            r = df[t] / total
            if r >= 0.5:
                continue
            if len(t) <= 2 and r > 0.08:
                continue
            out.append(t)
        return out

    def _corpus_top_term_hit_files(self, terms, pid=None):
        """语料包含性（治本·判别核）：返回查询**干净且稀有实体**出现在的作用域
        正文 filepath 列表（空=语料真缺该实体 → 拒答）。

        先 _clean_entities 剥离问句壳与跨域通用词，再排除全局高频词（出现在过半
        文件的词，如项目名 AIMH），只认稀有特异词作判别——命中文件才精准，不会
        退化成全库。任一稀有实体命中正文 → 返回命中文件（领域内事实，低置信返回）；
        全不命中 → 空列表（语料真缺该实体 → 拒答）。
        """
        cl = self._clean_entities(terms)
        if not cl:
            return []
        rare = self._rare_entities(terms, pid)
        crit = rare if rare else cl   # 纯项目名问题（无稀有实体）退化回全 clean
        # 候选预筛：search_blob 列 SQL 子串圈出可能命中的文件（O(候选) 而非全库
        # 逐文件读盘）。blob 只含 FM 层文本（检索层无正文）：blob 零命中时预筛
        # 降级全量文件列表（见 _corpus_blob_candidates），最终 _boundary_hit 在
        # 真正文上精确判定——正文按需打捞，精度不降。
        cands = self._corpus_blob_candidates(crit, pid)
        hits = []
        for fp in cands:
            b = self.read_body(fp)
            if not b:
                continue
            bl = b.lower()
            if any(self._boundary_hit(t, bl) for t in crit):
                hits.append(fp)
        return hits

    def _corpus_blob_candidates(self, crit, pid=None):
        """用 search_blob 列 SQL 子串圈候选文件（O(命中) 而非全库逐文件读盘）。

        仅当 _blob_ok【且】已全行填充（_blob_populated）时启用；否则退回
        _corpus_files 全量列表（旧库未 rebuild 兼容：列缺或全 NULL 时 LIKE 会漏
        NULL 行→假拒答，故降级 body 扫描）。下游 _boundary_hit 负责精确判定。

        blob 只含 FM 层文本（检索层无正文——设计铁律）：crit 词若只落在正文，
        LIKE 圈不出其所在文件 → 本函数返回空时【不可当作语料真缺】——调用方
        _corpus_top_term_hit_files 的最终判定域是 body（read_body + _boundary_hit），
        故空候选降级 _corpus_files 全量列表，正文词的命中判定交由 _boundary_hit
        在真正文上完成（打捞口径，与 _entity_in_corpus / _rare_entities 同源）。
        """
        # 仅当列已存在【且】已全行填充才走 SQL 快速路径；旧库未 rebuild 时
        # search_blob 全 NULL，LIKE 会静默漏 NULL 行→假拒答，故降级 body 扫描。
        if not (getattr(self, "_blob_ok", False) and self._blob_populated()):
            return self._corpus_files(pid)
        c = self._conn()
        parts, params = [], []
        for t in crit:
            if t:
                parts.append("search_blob LIKE ?")
                params.append("%" + str(t).lower() + "%")
        if not parts:
            return self._corpus_files(pid)
        sql = "SELECT filepath FROM events WHERE (" + " OR ".join(parts) + ")"
        if pid:
            sql += " AND (package_id=? OR package_id LIKE ? || '/%')"
            params += [pid, pid]
        rows = [r[0] for r in c.execute(sql, params).fetchall()]
        # blob（FM 层）零命中：词可能只在正文 → 降级全量文件列表，交给下游
        # _boundary_hit 在真正文上判定（正文按需打捞，检索层不预存正文）。
        return rows if rows else self._corpus_files(pid)

    def _entity_in_corpus(self, term, pid=None):
        """判别实体是否真在语料（正文 OR 锚点文本任一出现即算有）。

        供拒答层『稀有实体全缺失 → 硬拒答』做存在性判定。此处用【子串】而非
        _boundary_hit：拒答路径的误伤是「过拒」(false-present→不拒→把真答案
        当域外丢掉)，故偏宽松；而 rare 过滤已剔除高频 2 字碎片(计算/公司/世界…)，
        残留稀有实体子串命中基本就是同一实体，碰撞误删风险可忽略。比仅扫正文更稳：
        实体仅落在锚点(title/about/keywords)也识别得到，不会被误拒。
        （对照 _corpus_top_term_hit_files 用 _boundary_hit 是另一条路：它的误伤是
        「漏拒」，故偏严——两条路径误差方向本就相反，匹配口径应相反。）

        两段式（检索层无正文，正文按需打捞——设计铁律）：
          1. search_blob 列 SQL 子串判定（O(候选)，实测 9000 文件≈8ms）。blob 只含
             FM 层文本（title/summary/四要素/tags/linked/锚点 C+A+K），不含正文；
          2. blob 未命中 ≠ 语料无此词（词可能只在正文）→ 逐文件打捞：读 .md 正文
             子串确认（此时才读盘），正文永不进索引。真域外词付出一次全库扫描
             （57 包毫秒级；注释记载 3000 文件≈2.8s），换来「域内正文词不被假拒答」。
        """
        tl = (term or "").lower()
        if not tl:
            return False
        if getattr(self, "_blob_ok", False) and self._blob_populated():
            c = self._conn()
            sql = "SELECT 1 FROM events WHERE search_blob LIKE ?"
            params = ["%" + tl + "%"]
            if pid:
                sql += " AND (package_id=? OR package_id LIKE ? || '/%')"
                params += [pid, pid]
            if c.execute(sql, params).fetchone():
                return True
            # blob（FM 层）零命中：不就此断言语料缺失，落到逐文件打捞读正文确认
        for fp in self._corpus_files(pid):
            b = self.read_body(fp)
            if b and tl in b.lower():
                return True
            row = self._conn().execute(
                "SELECT anchors FROM events WHERE filepath=?", (fp,)).fetchone()
            if not row or not row[0]:
                continue
            try:
                anchors = json.loads(row[0]) or []
            except Exception:
                continue
            for a in (x for x in anchors if isinstance(x, dict)):
                blob = " ".join(str(a.get(k, "")) for k in
                               ("title", "Chapter", "about", "summary",
                                "locator"))
                blob += " " + " ".join(
                    str(t) for t in (a.get("tags") or a.get("keywords") or []))
                if tl in blob.lower():
                    return True
        return False

    def _relevance_filter(self, scored, terms, theta=0.5):
        """相关性硬阈值过滤（用户提案：匹配词加分 + 分界线）。

        每结果按命中查询词的 IDF 权重加分：rel(r) = Σ idf(t)·I(t∈r文本)。
        阈值 θ 以查询词总 IDF 权重为基准（默认 0.5 = 需覆盖≥半数 IDF 权重）。
        低于 θ 的结果视为不相关、直接丢弃；全丢 → 交由 _abstain 走 empty_pool 拒答。
        目的：治「corpus_missing_entity ANY-match 漏拒」——通用词(资料)命中即放行、
        却吐无关噪声的洞。IDF 加权确保高判别词(量子计算)权重 >> 通用词，分界线
        要求核心实体出现，通用词单命中跨不过线。
        """
        if not terms:
            return scored
        # 判别词表：剔除两类「撑阈值不撑命中」的 term——
        # ① 垃圾二元（是什/么类/型的/的记：滑动窗口碎词，语料罕见→IDF 虚高）；
        # ② 长中文整句串（len>4：机械切分保留的整问句，锚点永远精确命中不了，
        #    只把 w_total/thr 顶高，如「是哪几个铁律」idf=3.5）。
        # 二者都让跨包常见真词（架构/记忆/铁律，IDF 低）被误滤（design-journal 误拒根因）。
        # 仅作用于阈值计算；BM25 召回仍走完整 terms（不动召回）。
        disc = [t for t in terms
                if len(str(t)) <= 4 and not _is_garbage_bigram_late(str(t))]
        if not disc:
            return scored
        w_total = sum(self._idf(t) for t in disc)
        if w_total <= 0:
            return scored
        thr = theta * w_total
        # 自归一锚点：查询中判别力最强的单 term IDF，用作「命中判别词即保」的底线。
        # 治 over-abstain 根因：理解层 grounding 会把稀有变体
        # (如 黄蓝色的宝石/蓝钻/深海蓝橙焰钻石/那颗钻石) 注入 terms，其 IDF 撑高
        # w_total→thr 极高；而锚点只命中 宝石/示例信物 这类真判别词(rel 远<thr)
        # 被误删→empty_pool 过度拒答。补「锚点确含任一高判别实体词即保」通道：
        # 锚点若匹配到 ≥floor(=查询最强判别词 IDF 的一半) 的词，判定为相关、保活。
        # 纯噪声锚点只命中 作者/天气 等通用词(IDF 远低于 floor)→仍被滤→交由 _abstain 拒答。
        # floor 用【判别词表 disc 的 max IDF 的一半】而非全 terms 的 max——这是关键：
        # 若用全 terms（含 么类/忆架/是哪几个铁律 这类虚高 IDF 词）的 max，会顶爆 floor，
        # 使跨包常见真词(架构/记忆/铁律) 达不到 floor 而被误删（design-journal 历史误拒根因）。
        # 改用 disc（已剔垃圾二元+长整句串）的 max 派生 floor，虚高词被排除在 floor 基准外，
        # 真判别词得以保活。匹配段仍用全 terms（垃圾词命中给 rel 加分但权重小，无碍）。
        max_q_idf = max((self._idf(t) for t in disc), default=0.0)
        floor = 0.5 * max_q_idf
        bodies = {}
        out = []
        for a in scored:
            rid = a[0]
            if rid not in bodies:
                b = self._pkg_body(rid)
                bodies[rid] = (b or "").lower() if b else ""
            txt = ((a[1] or "") + " " + (a[2] or "") + " " + bodies[rid]).lower()
            match_idfs = [self._idf(t) for t in terms if t and str(t).lower() in txt]
            rel = sum(match_idfs)
            # 保持：(a) 相对覆盖达标 rel>=thr；或 (b) 锚点确含一个高判别实体词
            #       (max(match_idfs) >= floor)——治 grounding 膨胀阈值导致的有效命中误杀
            if rel >= thr or (match_idfs and max(match_idfs) >= floor):
                out.append(a)
        return out

    def _abstain(self, scored, q, terms, top_k, kappa, pid=None,
                 entity_gate=False):
        """四道闸聚合；返回结构化结果，让调用方区分「无答案」与「拒答」。

        闸序（任一命中即拒答，返回结构化结果让调用方区分「无答案」与「拒答」）：
          Gate0 empty_pool            空池
          GateA corpus_missing_entity 查询稀有实体全不在语料（仅 entity_gate，AI 接口）
          GateB corpus_missing_entity_mech  与语料零共现（仅机械兜底路径）
          Gate1 low_coverage          top_k 锚点 IDF 加权覆盖 < kappa → 拒答
          Gate2 out_of_scope          四要素越界
        放行时 confidence=high（覆盖 ≥ ABSTAIN_HIGH_K）/ low。
        拒答语义 = 「语料无该实体/覆盖不足」，锚点弱不单独构成拒答依据
        （body-only 事实的召回由正文 ### 段扫描与 hit_files 语料包含性信号承担，
        详见 design-journal《召回消歧管线设计（实现）》与 daylog-2026-09-05 #05）。
        """
        if not scored:                       # Gate 0 · 空池
            return {"answer": [], "abstain": True,
                    "reason": "empty_pool", "confidence": "none",
                    "message": ABSTAIN_DEFAULT_MSG}
        cov = self._coverage(scored, terms)
        # 反相拒答闸（治本，仅 AI 接口模式启用）：查询含稀有判别实体，但语料
        # 正文/锚点【任一都查不到】→ 域内确无该实体 → 直接拒答。本闸是 AI 接口
        # 路径上「语料无实体 → 拒答」的唯一执行者。
        # 仅当 terms 来自 AI 接口(keywords/decomposer) 时启用：机械切分
        # (normalize_terms) 抽不出『量子计算/回旋镖』这类复合实体，稀有过滤
        # 又会误剔真正在语料的实体（如 回旋 被设计文档举例引用而 >8% 文件 →
        # 误判缺失 → 过拒），故机械兜底路径不启用此闸，退回 coverage/out_of_scope
        # （G7 漏拒作为已知弱点，不阻断回归门）。真·功能接口在 AI 传复合关键词时
        # 才稳：复合词(≥3字)子串匹配可靠，不依赖脆弱的二元稀有过滤。
        if entity_gate:
            # AI 已解析出规范复合词，直接用【原始 keywords】做存在性判定，不再过
            # _clean_entities 机械清洗——否则 比特币(含"币")/股价(含"价") 会被
            # 功能字剥掉而误判缺失→漏拒。AI 关键词可信，逐个查语料子串；
            # 全缺失 → 域内确无该实体 → 硬拒答。（≥2 字才计入，过滤单字噪声）
            ents = [t for t in terms if t and len(str(t).strip()) >= 2]
            if ents:
                present = [t for t in ents if self._entity_in_corpus(t, pid)]
                if not present:
                    return {"answer": [], "abstain": True,
                            "reason": "corpus_missing_entity", "confidence": "none",
                            "message": ABSTAIN_DEFAULT_MSG}
        # 机械兜底拒答闸（方向 4，零依赖、域自适应）：无 AI keywords 时，若查询与
        # 语料【零共现】（无任何 ≥2 字 / latin≥2 词重叠）→ 最外国语料 → 拒答。
        # 只增不减：域内题的核心判别词必在语料 → 必有共现 → 不触发，回归不受影响。
        # 复合实体域外题（量子计算，含子词"计算"在语料）机械不可达，仍由 AI 接口兜。
        if not entity_gate:
            try:
                from .refine import corpus_overlap_absent
                if corpus_overlap_absent(self, q):
                    return {"answer": [], "abstain": True,
                            "reason": "corpus_missing_entity_mech",
                            "confidence": "none",
                            "message": ABSTAIN_DEFAULT_MSG}
            except Exception:
                pass
        if cov < kappa:                      # Gate 1 · 覆盖不足且无语料命中
            return {"answer": [], "abstain": True,
                    "reason": "low_coverage", "confidence": "none",
                    "message": ABSTAIN_DEFAULT_MSG}
        if self._out_of_scope(q, scored, pid):    # Gate 2 · 四要素越界
            return {"answer": [], "abstain": True,
                    "reason": "out_of_scope", "confidence": "none",
                    "message": ABSTAIN_DEFAULT_MSG}
        conf = "high" if cov >= ABSTAIN_HIGH_K else "low"
        return {"answer": scored[:top_k], "abstain": False,
                "reason": "", "confidence": conf}




# 变更快照系统已废弃（R59 续3）：write 不再落 changes/，
# 修改标记改由 front-matter 的 `updated:` 字段承担（每次 write 刷新）。


# ---------------------------------------------------------------------------
# 查询分词（query / query_anchors 共用，保证两层口径一致）
# ---------------------------------------------------------------------------
