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
import sqlite3
import math
import os
import re
from collections import Counter

from .. import recall_obscure as ro
from .. import routing
from .. import scoring_coeffs as C
from .aggregate_time import (  # S3 已外拆的时间意图/闸，无循环依赖
    TimeHint, parse_time_hint, _is_union_query, _time_tiebreak,
)


def _flat_variants_late(fld):
    from .. import hma_core
    return hma_core._flat_variants(fld)


def _is_garbage_bigram_late(t):
    from .. import hma_core
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
                from ..refine import corpus_overlap_absent
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


def normalize_terms(ql):
    """把查询串切成用于匹配的 term 列表。

    1. 按 '+'/空白 切分（AIMH 特征词查询形态：蓝+钻石 / 孤品 蓝钻，与
       resolve_query._query_tokens 同口径）；剥去每个 term 首尾标点。
    2. 滤掉英文功能词；若全被滤空则退回未过滤结果
       （保证 "the" 这类查询本身仍可检索）。
    3. 中文无空格无 '+' → 整句为单个 term，停用词表纯 ASCII 故不受影响。
    """
    raw = [t.strip(_PUNCT) for t in re.split(r"[+\s]+", ql)]
    raw = [t for t in raw if t]
    kept = [t for t in raw if t not in _STOPWORDS]
    return kept or raw

def _flat_variants(fld):
    """四要素字段 → 扁平 [规范名 + 变体] 列表（兼容 list / dict / JSON 串）。

    用于实体词表（_entity_vocab）、字段加权（_pkg_fields）等需要"所有可识别实体
    名"的场景；V2 dict 与旧 list 统一成同一扁平表示。
    """
    if not fld:
        return []
    if isinstance(fld, str):
        try:
            fld = json.loads(fld)
        except Exception:
            return []
    out = []
    if isinstance(fld, dict):
        for k, vs in fld.items():
            out.append(k)
            out.extend(vs or [])
    elif isinstance(fld, list):
        out.extend(fld)
    return out

def _is_garbage_bigram(t):
    return len(t) == 2 and (t[0] in _GARBAGE_FUNC or t[1] in _GARBAGE_FUNC)

def _feat_alt_match(f, q):
    """特征 token 可能含 '/' 分隔的同义表面（如「黄/橙」「黑/暗」）。

    语义：该属性的任一表面形式在查询 q 中出现即算命中（OR）。
    无 '/' 时退化为整串子串匹配。
    """
    return any(part and part in q for part in f.split("/"))

# ---------------------------------------------------------------------------
# 召回消歧：歧义门 + 特征判别澄清（实体歧义由 Memory.resolve_query 承担）
# ---------------------------------------------------------------------------
def _norm(s):
    """归一化：小写并去两端空白。判别特征/查询比较的统一口径。"""
    return (s or "").lower().strip()

def _entity_key(title):
    """实体去重键：从标题抽取规范名，消除「（别名」/「(别名」/「 · 分章」造成的假歧义，
    使同一角色的 基础包/拓展/背景故事 多行归并为同一实体。"""
    t = (title or "").strip()
    for sep in ("（", "(", " · "):
        t = t.split(sep)[0].strip()
    return t

def _field_term_hit(term, field_tokens):
    """topic/tags 命中判定：ascii 词要求【整词/规范名精确匹配】，防
    corpus_missing⊂corpus_missing_entity 这类子串误判把无关包整包顶起；
    CJK 词允许子串（架构⊂存储架构 属期望命中）。field_tokens 为小写后的
    topic 规范名/变体 + 包级 tags 集合。"""
    if any(c.isascii() and c.isalnum() for c in term):
        return term in field_tokens
    return any(term in t for t in field_tokens)

def _anchor_score(at, asum, atags, abody, ql, terms, w):
    """单个「文本块」（一段锚点，或一个事件包的全部锚点拼成的虚拟块）的计分。

    覆盖度模型（废除次数加分）：逐字段只取【最高命中档】加一次，不随命中词数
    线性累加；查询词覆盖度用饱和因子折总（coverage_sat），多词命中边际递减，
    避免长/多字段文档靠堆词虚高（如「主义」二元碎片在四字段各加一次）。
    ql 为原始查询串；terms 为归一化后的 term 列表；w 为 term→权重映射
    （idf 模式保留签名，但覆盖度模型不再按 w[t] 逐词累加）。
    """
    s = 0
    if ql == at:
        s += C.ANCHOR_TITLE_EXACT
    elif any(t in at for t in terms):   # 标题：命中即一次，不随词数累加
        s += C.ANCHOR_TITLE_SUBSTR
    if any(t in asum for t in terms):   # 摘要：命中即一次
        s += C.ANCHOR_SUMMARY_SUBSTR
    # tag：精确 > 子串，命中即一次（break 已保证只加一次）
    tag_hit_exact = any(ql == tg for tg in atags)
    tag_hit_sub = any(any(t in tg for t in terms) for tg in atags)
    if tag_hit_exact:
        s += C.ANCHOR_TAG_EXACT
    elif tag_hit_sub:
        s += C.ANCHOR_TAG_SUBSTR
    # 段内正文扫描（修订核心）：L2 现在能看见段内文字，不仅是首句摘要
    if ql in abody:
        s += C.ANCHOR_BODY_EXACT
    elif any(t in abody for t in terms):  # 正文子串：命中即一次
        s += C.ANCHOR_BODY_SUBSTR
    # 覆盖度奖励（废除次数加分的核心）：查询词只要被本锚点覆盖（命中≥1 个真实词），
    # 给一次性基准分 × 饱和因子——多词命中边际递减，不再按命中词数 ×N 虚高。
    covered = set()
    for t in terms:
        if (t in at) or (t in asum) or (t in abody) or any(t in tg for tg in atags):
            covered.add(t)
    if covered:
        real_hits = [t for t in covered if not _is_garbage_bigram(t)]
        garbage_hits = [t for t in covered if _is_garbage_bigram(t)]
        if real_hits:
            # 覆盖度饱和：命中词数 n → 1-exp(-SAT_K*n)，n=1→0.45, n≥5→>0.95
            s += C.KW_FIXED * C.coverage_sat(len(real_hits))
        # 垃圾二元仅给极小防御分（机械流兼容，不靠命中数虚高）
        s += C.KW_BIGRAM_BONUS * len(garbage_hits)
    return s

def _search_blob(pkg):
    """构造小写可检索 blob（标题+四要素+tags+linked+各锚点 Chapter/about/keywords+body），
    供 query_anchors 以 SQL LIKE 做【语义等价】候选预筛，
    取代逐行全扫+json.parse+逐锚点切章。LIKE '%term%' 命中的行，必含会被
    _anchor_score 子串匹配得分的锚点（超集）→ 预筛零召回回归。"""
    parts = [pkg.title or "", pkg.summary or ""]
    for col in (pkg.person, pkg.topic, pkg.location):
        if isinstance(col, dict):
            for k, vs in col.items():
                parts.append(k)
                if isinstance(vs, list):
                    parts.extend(str(v) for v in vs)
        elif isinstance(col, str):
            parts.append(col)
    if pkg.event_date:
        parts.append(pkg.event_date)
    if isinstance(pkg.tags, list):
        parts.extend(str(t) for t in pkg.tags)
    elif isinstance(pkg.tags, str):
        parts.append(pkg.tags)
    if isinstance(pkg.linked, list):
        parts.extend(str(t) for t in pkg.linked)
    for a in (pkg.anchors or []):
        if not isinstance(a, dict):
            continue
        parts.append(a.get("Chapter") or a.get("title") or "")
        parts.append(a.get("about") or a.get("summary") or "")
        for tg in (a.get("tags") or a.get("keywords") or []):
            parts.append(str(tg))
    parts.append(pkg.body or "")
    return " ".join(parts).lower()

def _norm_name(s):
    """人名归一：去空白与分隔符（·/空格/点等），统一小写，便于「名称比对」。

    例：'托尼·斯塔克' / '托尼 斯塔克' → '托尼斯塔克'，与词表归一形式一致比对。
    """
    return re.sub(r"[^a-z0-9一-鿿]", "", str(s).lower())

def _share_surname(a, b):
    """同姓异人判定：归一名 a、b 不同，但末尾两字（中文姓常落末位，如 斯塔克）相同。

    例：'托尼斯塔克' 与 '霍华德斯塔克' 末尾同 '斯塔克' → 同姓异人；
        '托尼斯塔克' 与 '托尼斯塔克' 相同 → 非异人（精确命中走另一分支）。
    """
    if not a or not b or a == b:
        return False
    return len(a) >= 2 and len(b) >= 2 and a[-2:] == b[-2:]

def _scope_clause(scope, root):
    """返回 (sql_fragment_or_None, [params])，用于聚焦检索收束候选集。

    scope 为空 → (None, []) 即全仓（零回归）。
    scope 为绝对路径或相对 root 的路径 → 归一为 'REPLACE(filepath,'\\','/') LIKE ?'
    并拼入参数（双端 REPLACE 归一分隔符，与 index.db 存储的「绝对路径」形态对齐）。
    """
    if not scope:
        return None, []
    p = scope if os.path.isabs(scope) else os.path.join(root, scope)
    p = os.path.normpath(p).replace("\\", "/")
    return "REPLACE(filepath,'\\','/') LIKE ?", ["%" + p + "%"]


# 查询归一共用的标点集与英文功能词表：机械兜底路径（normalize_terms 按 [+\s] 切分后
# strip 标点、滤功能词）与垃圾二元判定（_is_garbage_bigram）共用。
_PUNCT = " \t\r\n\"'`,.;:!?()[]{}<>/\\|@#$%^&*+=~_" + \
         "\u201c\u201d\u2018\u2019\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f" + \
         "\uff08\uff09\u300a\u300b\u300c\u300d\u3010\u3011\u2026\u2014\u2013"

# 英文功能词。检索按「词命中就加分」计分，这类词在任何一段文本里都会出现，
# 会给全部候选送上等量底分，把判别词的信号淹掉（实测：跨对话的无关段落
# 仅靠 when/did/go/to/the 就能压过正确段落）。纯 ASCII，对中文查询无副作用。
_STOPWORDS = frozenset("""
a an the this that these those
am is are was were be been being
do does did done doing
have has had having
i me my mine myself you your yours he him his she her hers it its
we us our ours they them their theirs
what when where who whom whose which why how
to of in on at for with by from into onto over under above below about as
and or but if then so because than while during
not no nor yes
there here out up down off very just also any all each every both such own same too only
will would shall should can could may might must
s t re ve ll d m o
""".split())

# 零-ML 中文二元噪声判定：长中文串被滑成所有相邻二元，其中含语法/代词/否定/数词/
# 指代/助词/介词字符的（我是/是不/不是/是设/计过/过一/一个/个角…）视为噪声二元，
# 只拿 _KW_BIGRAM_BONUS 极小固定分；内容二元（用户/角色/设计/武器/重构…）不受影响、拿满 _KW_FIXED。
_GARBAGE_FUNC = set("的了吗呢吧啊呀嘛咯是的不没我你他她它咱们这那哪些个之与和或但而也把被让给对从向在到过着地得一二三四五六七八九十百千万什怎怎么忆几哪能可很最")

# 歧义门阈值：去重后实体候选数达到此值即判歧义 → 交交互澄清（默认 2）。
MIN_CANDIDATES = 2

# 四要素软加权（理解层字段族）用的地点/月份词典。确定性、零 ML。
_LOC_WORDS = frozenset({
    'home', 'school', 'restaurant', 'park', 'office', 'gym', 'hospital', 'airport',
    'library', 'cafe', 'bar', 'store', 'mall', 'beach', 'lake', 'city', 'town',
    'kitchen', 'garden', 'building', 'university', 'college', 'work', 'apartment',
})

# 四要素权重（topic 用连续命中数，其余 0/1）：person / time / topic / location
# 系数集中到 scoring_coeffs.FIELD_W_*
_FIELD_W = (C.FIELD_W_PERSON, C.FIELD_W_TIME, C.FIELD_W_TOPIC, C.FIELD_W_LOCATION)

# 字段加权折进 score 的封顶参数：mc/bonus 不再作主排序键，而是作为【有上限的加法项】
# 折进文本分，确保"文本相关度"为主排序、字段仅作轻推（修 T11/T08/T03 整包被 topic/tags
# 子串顶到真答案前）。_FIELD_CAP=字段贡献不超过文本分×此比例。
_FIELD_NUDGE = C.FIELD_NUDGE   # 每命中 1 个结构化要素的基础 nudges（再经 _FIELD_CAP 封顶）

_FIELD_CAP = C.FIELD_CAP

class RetrievalMixin:
    """检索线方法集合，由 hma_core.Memory 继承（S4b 拆分，方案 A：Mixin）。

    方法体从 hma_core.Memory 逐字搬入，未作任何语义修改；self.* 依赖（含机械层
    _abstain/_relevance_filter 与 Memory 侧 _conn/_idf/_kw_index 等）由 MRO 解析。
    """


    # ---- 写入路径（实时，Agent 直写 .md + 确定性 upsert 索引）-----------
    def query(self, q, top_k=5, use_vector=False, package_id=None,
              keywords=None, decomposer=None, scope=None):
        """确定性检索：关键词命中 id/title/alias/tag/summary。
        返回 [(id, title, summary, score), ...]（已按确定性规则排序）。

        package_id=None（默认）→ 限定在当前 Memory 的包作用域内
        （repo 级句柄 package_id="" 即全局扫描）；传 "" 显式即全局；
        传具体包 id（如 "原创角色/luzhao"）则只扫该包。

        keywords= / decomposer= 是理解层 REFINE / 复合实体解析的透传入口：
        AI 解析出的词并回查询串参与包级打分（零-ML 不参与理解）。机械拆词
        仅在两者皆缺时由调用方自行处理，本方法在 AI 显式给词时把词并入 ql。

        复杂度 O(n)：全表/包 fetchall + 逐行打分。个人记忆规模（<10⁴ 包）
        实测 <50ms。若未来超万级且 json.loads 开销可感，可加 SQL LIKE
        预过滤缩小候选（不改表、可重建、不引入状态），无需倒排/FTS。
        """
        # AI 关键词接口透传：keywords 优先，其次 decomposer 回调，最后原句。
        if keywords:
            ql = (q + " " + " ".join(str(k) for k in keywords)).lower().strip()
        elif callable(decomposer):
            dq = decomposer(self, q) or ""
            ql = (q + " " + dq).lower().strip() if dq else q.lower().strip()
        else:
            ql = q.lower().strip()
        # 召回只走 AI 流：无 keywords/decomposer 时不再机械 CJK 二元拆词（铁律），
        # 整句作为单一 term 处理；实体级召回由 AI 理解层传 keywords 负责。
        c = self._conn()
        pid = self.package_id if package_id is None else package_id
        scl, spar = _scope_clause(scope, self.root)
        if pid:
            # q-2（嵌套检索）：范围搜"哲学"也命中"哲学/尼采"子树——
            # package_id=?（本节点）OR package_id LIKE ?||'/%'（所有子孙）。
            # 确定性（无热度/新鲜度权重），不破 §13；现有包均扁平，零回归。
            sql = (
                "SELECT filepath,title,summary,person,topic,location,tags,linked,pkage_updated,event_date "
                "FROM events WHERE package_id=? OR package_id LIKE ? || '/%'")
            params = [pid, pid]
            if scl:
                sql += " AND " + scl
                params += spar
            rows = c.execute(sql, params).fetchall()
        else:
            sql = (
                "SELECT filepath,title,summary,person,topic,location,tags,linked,pkage_updated,event_date "
                "FROM events")
            params = []
            if scl:
                sql += " WHERE " + scl
                params += spar
            rows = c.execute(sql, params).fetchall()

        scored = []
        for fp, title, summary, pj, tj, lj, tags_j, linked_j, updated, edate in rows:
            rid = os.path.splitext(os.path.basename(fp))[0]   # 文件名 stem 作 id
            person_aliases = _flat_variants(pj)
            other_aliases = _flat_variants(tj) + _flat_variants(lj)
            tags = json.loads(tags_j or "[]")
            s = self._score(ql, rid, title, summary, person_aliases, other_aliases, tags)
            if s > 0:
                scored.append((rid, title, summary, s, updated, edate))

        # 确定性排序：分数降序 → 事件时间近因 tie-break（无事件时间则退化写入时间）→ id 升序。
        # 机制A：仅在分数相等的候选间用事件时间裁决先后（不破 §13 反遗忘；全量时间重排会
        # 把 daylog 顺带提及的低相关新条目顶到旧高相关条目前，故只做平局裁决）。
        scored.sort(key=lambda x: (-x[3], _time_tiebreak(x[5], x[4]), x[0]))
        return [(x[0], x[1], x[2], x[3]) for x in scored[:top_k]]

    def _build_clarify(self, q, cands, idx, global_count):
        """构造特征判别澄清载荷。

        对每个候选实体算『独有弧段』= 自身特征 − 其他候选特征并集（Venn 不相交部分），
        按特异性梯度排序：越靠近圆心（拥有该特征的实体越少=IDF 越高 / 中心度 tier 越强）排越前。
        cands: [(rid, title, summary, score), ...]（已按实体去重）。
        返回 {"mode":"ambiguity","candidates":[{ekey,title,rid,unique:[...]}]}。"""
        ekeys = []
        for (_, t, _, _) in cands:
            ek = _entity_key(t)
            if ek in idx and ek not in ekeys:
                ekeys.append(ek)
        feats = {ek: idx[ek]["features"] for ek in ekeys}
        # 排除『仅出现在锚点 keywords、不在任何结构化字段』的共现噪声 token
        # （如故事里顺带提到的配角名 示例人物/弗瑞）——它们不是实体自身特征，
        # 亮出来会误导澄清。结构化特征 = person/topic/location 规范名 + 变体。
        anchor_only = self._anchor_only_tokens()
        out = []
        for (rid, title, summary, score) in cands:
            ek = _entity_key(title)
            if ek not in feats:
                continue
            own = feats[ek]
            others_union = set().union(
                *[set(feats[o]) for o in ekeys if o != ek]) if len(ekeys) > 1 else set()
            # 独有弧段 = 自身特征 − 其他候选特征并集 − 锚点共现噪声 → 只亮实体自己的特征
            unique_feats = [f for f in own
                            if f not in others_union and f not in anchor_only]
            # 特异性梯度排序：全局拥有实体数升序（IDF 高=靠近圆心）→ 中心度 tier 降序 → CJK 优先
            unique_feats.sort(key=lambda f: (
                global_count.get(f, 9999),
                -own[f],
                0 if not f.isascii() else 1,
                -len(f),
            ))
            out.append({
                "ekey": ek,
                "title": idx[ek]["title"],
                "rid": rid,
                "summary": summary,
                "unique": unique_feats[:6],
            })
        return {"mode": "ambiguity", "candidates": out}

    def _coverage_gate(self, q, results, top_k=10, keywords=None, decomposer=None):
        """软覆盖门：澄清之前判『区分词能否唯一锁定候选』。

        区分词 = 查询 token 中仅命中 top-K 候选恰好 1 个者（如 纯净蓝 / 孤品 / 2005）。
        若全部区分词指向同一候选 → 直接唯一返回（跳过澄清）；否则 None → 回落歧义门。
        软门（非硬 AND 过滤）→ 不误杀、不删空，守 anti-over-abstain。

        匹配用包级可检索 blob 的连续子串（_search_blob），与沙箱原型一致。
        区分词检测范围 = 召回 top-K 池。
        """
        cands = [rid for rid, *_ in results[:top_k]]
        if len(cands) < 2:
            return None
        toks = self._query_tokens(q, keywords=keywords, decomposer=decomposer)
        if not toks:
            return None
        # 每候选包级 blob（小写）做连续子串包含判定
        blobs = {}
        for rid in cands:
            try:
                pkg = self.read(rid)
            except Exception:
                pkg = None
            blobs[rid] = _search_blob(pkg).lower() if pkg else ""
        disc = {}  # token -> 唯一命中候选
        for t in toks:
            hits = [rid for rid in cands if t in blobs[rid]]
            if len(hits) == 1:
                disc[t] = hits[0]
        if not disc:
            return None
        covered = set(cands)
        for t, hit in disc.items():
            covered &= {hit}
        if len(covered) == 1:
            return covered.pop(), list(disc.keys())
        return None

    def resolve_query(self, q, top_k=5, use_vector=False, package_id=None,
                      allow_clarify=True, multihop=False, scope=None,
                      keywords=None, decomposer=None, allow_abstain=False):
        """召回消歧入口（B 类 resolver）：在确定性 query() 召回之上做实体歧义判定。

        流程：query() 关键词召回 → 按实体键去重 → 歧义门（≥2 实体候选 → 澄清）
              → 负特征差集塌缩（对偶算子：排除带否定特征的实体）
              → 特征判别澄清（亮出每个候选的『独有弧段』，按特异性梯度排序）。

        返回 dict：
          · 非歧义：{"decision":"return","results":[(rid,title,summary,score),...],"stage":...}
          · 歧义  ：{"decision":"clarify","payload":{"mode":"ambiguity",
                     "candidates":[{ekey,title,rid,summary,unique:[判别特征]}]},"stage":"clarify"}
          · 拒答  ：{"decision":"abstain","reason":"corpus_missing_entity"/"empty_pool",
                     "results":[]}（仅 allow_abstain=True 且 ai_mode 时可能触发）
        澄清开关是『歧义（≥2 实体）』而非『零命中』；歧义时亮出独有弧段让用户用
        特征指认，而非硬猜或逼回忆名字。向量全程不入场。

        allow_abstain=True 且 keywords/decomposer（AI 接口）传入时，补硬拒答闸：
        所有判别实体在语料（正文+锚点）都查不到 → 直接 abstain(corpus_missing_entity)，
        不再依赖 coverage 兜底被二元噪声抬过 κ。域内题实体必在语料 → 不误拒。
        """
        internal_topk = max(top_k * 3, 20)
        if multihop:
            # 多跳：先把单跳种子沿 linked 扩簇，再把扩簇结果喂给既有实体歧义门
            # （机制复用：实体→簇，其余 Venn/梯度/双算子原样作用在簇集上）。
            results = self.recall_multihop(q, top_k=internal_topk,
                                           package_id=package_id,
                                           keywords=keywords, decomposer=decomposer)
        else:
            results = self.query(q, top_k=internal_topk, use_vector=use_vector,
                                 package_id=package_id, scope=scope,
                                 keywords=keywords, decomposer=decomposer)
        # AI 接口硬拒答闸（corpus_missing_entity）：仅 allow_abstain 且 ai_mode
        # （keywords/decomposer 来自理解层）时启用。判别实体在语料（正文+锚点）
        # 任一都查不到 → 域内确无该实体 → 直接拒答，不靠 coverage 兜底被二元噪声抬过 κ。
        # 域内题的判别实体必在语料 → present 非空 → 不触发，回归不受影响。
        if allow_abstain and (keywords is not None or callable(decomposer)):
            ents = list(keywords) if keywords is not None else []
            present = [t for t in ents if self._entity_in_corpus(t, package_id)]
            if not present:
                return {"decision": "abstain",
                        "reason": "corpus_missing_entity", "results": []}
        # 机械兜底拒答闸（补 resolve_query 主路径缺口）：非 ai_mode 且 query() 主召回
        # 为空时，若查询与语料零共现→域内确无该实体→拒答。与 query_anchors._abstain
        # 方向 4 同口径，使「拒答层默认开启(V1.0)」在 MCP 主路径也真正生效（否则越域
        # 查询只回空结果、MCP 显示 (no match) 而非显式 (ABSTAIN)，等于拒答层没接）。
        elif allow_abstain and not results:
            try:
                from ..refine import corpus_overlap_absent
                if corpus_overlap_absent(self, q):
                    return {"decision": "abstain",
                            "reason": "corpus_missing_entity_mech", "results": []}
            except Exception:
                pass
        # === 覆盖门（软·强信号快捷通道）：澄清之前先判『区分词能否唯一锁定』===
        # 查询 token 中仅命中 top-K 恰好 1 候选者即区分词；若全部区分词指向同一
        # 候选 → 直接唯一返回（跳过澄清）。无区分词 / 区分词分裂 → 回落既有歧义门，
        # 不误杀、不删空（守 anti-over-abstain）。沙箱原型已验证：唯一召回 100% /
        # 误杀 0 / paraphrase 安全。
        _gate = self._coverage_gate(q, results, top_k=max(top_k * 2, 10),
                                    keywords=keywords, decomposer=decomposer)
        if _gate:
            _winner, _disc = _gate
            _wr = next((r for r in results if r[0] == _winner), None)
            if _wr is not None:
                return {"decision": "return",
                        "results": [(_wr[0], _wr[1], _wr[2], _wr[3])],
                        "stage": "coverage_gate", "ambiguous": False,
                        "discriminators": _disc}
        if not allow_clarify:
            # 空结果兜底：查询确实没查到 → 明确「没查到」(abstain) 而非「成功的空列表」。
            # 语义：resolve_query 契约 = return(有结果) / abstain(没查到) / clarify(歧义)，
            # 空 return+[] 会让调用方误以为「查到了但没结果」。仅包级查询（results 来自
            # query()）为空时触发；锚点级 query_anchors 是另一入口，不受影响。
            if not results:
                return {"decision": "abstain",
                        "reason": "no_match",
                        "results": [], "stage": "keyword", "ambiguous": False}
            return {"decision": "return", "results": results[:1],
                    "stage": "keyword", "ambiguous": False}

        # 实体去重：同一 ekey 的多行/多分章 → 一个候选，取最高分那行作代表
        best = {}
        for (rid, title, summary, score) in results:
            ek = _entity_key(title)
            if ek not in best or score > best[ek][3]:
                best[ek] = (rid, title, summary, score)
        distinct = sorted(best.values(), key=lambda x: -x[3])

        if len(distinct) < MIN_CANDIDATES:
            # 空结果兜底（同 not allow_clarify 分支）：包级查询没查到 → 明确 abstain
            if not distinct:
                return {"decision": "abstain",
                        "reason": "no_match",
                        "results": [], "stage": "keyword", "ambiguous": False}
            return {"decision": "return",
                    "results": [(r[0], r[1], r[2], r[3]) for r in distinct][:1],
                    "stage": "keyword", "ambiguous": False}

        idx = self._entity_feature_index(package_id)
        cands = [(r[0], r[1], r[2], r[3]) for r in distinct if _entity_key(r[1]) in idx]
        if len(cands) < MIN_CANDIDATES:
            return {"decision": "return",
                    "results": [(r[0], r[1], r[2], r[3]) for r in distinct][:1],
                    "stage": "keyword", "ambiguous": False}

        # 负特征差集塌缩（对偶算子）：排除带否定特征的候选实体
        negs = self._neg_features_from_query(q, idx)
        dropped = []
        if negs:
            kept = []
            for (rid, title, summary, score) in cands:
                ek = _entity_key(title)
                if set(idx[ek]["features"].keys()) & negs:
                    dropped.append(ek)
                else:
                    kept.append((rid, title, summary, score))
            if len(kept) == 1:
                r = kept[0]
                return {"decision": "return", "results": [(r[0], r[1], r[2], r[3])],
                        "stage": "negation", "ambiguous": True, "dropped": dropped}
            if len(kept) >= MIN_CANDIDATES:
                cands = kept

        # 全局特征实体数（= IDF 分母）：每个特征被多少个不同实体拥有（越独占越靠近圆心）
        global_count = {}
        for ent in idx.values():
            for f in ent["features"]:
                global_count[f] = global_count.get(f, 0) + 1

        # ② 并集意图识别（缺口修复）：查询含「都/全/各自/分别/共同/所有」等聚合词时，
        # 用户要的是多实体共同内容，而非在实体间二选一 → 抑制歧义澄清门，
        # 直接合并所有被召回实体的代表结果返回（union），避免误触发 clarify 反问用户。
        if _is_union_query(q) and len(distinct) >= 2:
            return {"decision": "union",
                    "results": [(r[0], r[1], r[2], r[3]) for r in distinct][:top_k],
                    "stage": "union", "ambiguous": False,
                    "note": "聚合意图（都/全/各自/分别/共同/所有），已合并多实体结果而非要求消歧"}

        payload = self._build_clarify(q, cands, idx, global_count)
        return {"decision": "clarify", "payload": payload, "stage": "clarify",
                "ambiguous": True, "dropped": dropped}

    def _idf(self, t):
        """返回 term t 的 IDF 权重；首次调用时懒构建文档频率表并缓存。"""
        if getattr(self, "_idf_docs", None) is None:
            self._build_idf()
        if t not in self._idf_df:
            n = sum(1 for d in self._idf_docs if t in d)
            # 去地板：常见词(n≈N)→idf≈0，稀有词(n≪N)→保留真实权重。
            # 让“命中稀有判别词”压倒“命中一大堆常见词”，是小索引跨包判别的关键。
            self._idf_df[t] = max(0.0, math.log((self._idf_N + 1) / (n + 1)))
        return self._idf_df[t]

    def _bm25_corpus(self, pid):
        """懒构建 BM25 语料统计（df / doc_len / N / avgdl），按 pid 过滤缓存。

        仅扫描一次 `events`（与 query_anchors 同一过滤口径），之后复用；
        每次检索调用不再重扫，热路径零额外扫描。
        """
        if getattr(self, "_bm25_cache", None) is None:
            self._bm25_cache = {}
        key = pid or ""
        if key in self._bm25_cache:
            return self._bm25_cache[key]
        c = self._conn()
        if pid:
            rows = c.execute(
                "SELECT filepath,title,anchors FROM events "
                "WHERE package_id=? OR package_id LIKE ? || '/%'",
                (pid, pid)).fetchall()
        else:
            rows = c.execute("SELECT filepath,title,anchors FROM events").fetchall()
        pkg_tok = {}
        doc_len = {}
        for rid, title, aj in rows:
            try:
                anchors = json.loads(aj or "[]")
            except Exception:
                anchors = []
            # 文档标题注入锚点可检索文本：标题是区分同名/同主题文档的最强判别信号。
            # 仅索引锚点 Chapter/about/keywords+正文会导致「仅由标题区分」的文档（如
            # 「召回消歧管线设计（实现）」）无法被标题词查询命中。标题在文档级拼接
            # 一次（不随锚点数重复），避免权重被锚点数放大。
            body = ((title or "") + "\n" + "\n".join(
                self._anchor_body(rid, a) for a in anchors
                if isinstance(a, dict))).lower()
            toks = self._RERANK_TOK.findall(body)
            pkg_tok[rid] = Counter(toks)
            doc_len[rid] = len(toks)
        N = len(pkg_tok)
        df = Counter()
        for ctr in pkg_tok.values():
            for t in ctr:
                df[t] += 1
        avgdl = (sum(doc_len.values()) / N) if N else 1
        stats = {
            "pkg_tok": pkg_tok,
            "doc_len": doc_len,
            "df": df,
            "N": N,
            "avgdl": avgdl,
            "pkg_set": {rid: set(ctr) for rid, ctr in pkg_tok.items()},
        }
        self._bm25_cache[key] = stats
        return stats

    def _rerank(self, scored, ql, pid):
        """对已捞到的候选做确定性 BM25 重排（含词项覆盖奖励）。

        scored: [(pkg_id, title, summary, locator, score), ...]
        返回按 BM25+覆盖 降序重排后的列表（确定性 tie-break：包 id、标题）。
        """
        stats = self._bm25_corpus(pid)
        qterms = self._RERANK_TOK.findall(ql.lower())
        qset = set(qterms)
        df = stats["df"]
        N = stats["N"]
        avgdl = stats["avgdl"]
        pkg_tok = stats["pkg_tok"]
        doc_len = stats["doc_len"]
        pkg_set = stats["pkg_set"]

        def score(entry):
            rid = entry[0]
            toks = pkg_tok.get(rid)
            if not toks:
                return float("-inf")
            dl = doc_len.get(rid, 1) or 1
            s = 0.0
            for qt in qterms:
                d = df.get(qt, 0)
                if d == 0:
                    continue
                idf = math.log(1 + (N - d + 0.5) / (d + 0.5))
                tf = toks[qt]
                s += idf * (tf * (self._RERANK_K1 + 1)) / (
                    tf + self._RERANK_K1 * (1 - self._RERANK_B +
                                            self._RERANK_B * dl / avgdl))
            cov = (len(qset & pkg_set.get(rid, set())) / len(qset)) if qset else 0.0
            return s + self._RERANK_COV_W * cov

        ranked = sorted(scored, key=lambda e: (-score(e), e[0], e[1]))

        # dK 瀑布裁切（铁律·用户 2026-08-22 钉死）：75 = 相邻分差基准（CUTOFF_GAP_FLOOR）。
        # 从 top1 往下扫，第一个 d_k > 75 处 -> top_{k+1} 及之后全部裁切、扫描立即终止；
        # 全程 d_k <= 75 -> 全保留（同分簇/弱命中/纯噪声均属此）。非绝对分阈值、非逐段裁切。
        # ★ 重要：本裁切的 d_k 取的是 `entries[k][4]` —— 即**锚点原始分**(_anchor_score 量级
        # 150×n)，不是上面 score(e) 的 BM25 分。sorted 只重排顺序、不改元组内容，故裁切键
        # 仍是原始锚点分（这正是铁律设计意图：75 针对锚点分制）。切勿误以为"作用在 BM25 分
        # 上 75 过大永不触发"——那是分制误读（2026-08-24 复核实测：示例信物池 9→裁2、
        # 尼采 17→6、存在主义 19→2，裁切真实且剧烈触发）。
        # 裁切逻辑收编至 recall_obscure.waterfall_cut（与沙箱 dk 实验稿同源、单点维护）。
        return ro.waterfall_cut(ranked, C.CUTOFF_GAP_FLOOR)

    def query_anchors(self, q, top_k=5, package_id=None, dedup_packages=False,
                      idf=True, package_agg=False, rerank=False, reform=True,
                      use_field_weights=True, use_features=False,
                      allow_abstain=False, kappa=None,
                      context=None, decomposer=None, keywords=None, scope=None):
        """细粒度召回：在锚点层检索，返回命中的子事件。
        返回 [(pkg_id, anchor_title, anchor_about, locator, score), ...]（anchor_about = 锚点 about 字段，summary 仅兼容回退）。
        用于「1 个包 + 多锚点」场景下的精准故事召回。
        package_id 过滤语义同 query。

        dedup_packages=True → 每个事件包最多保留得分最高的一个锚点。
        默认 False，保留「同包多锚点」的精准段落召回（Demo 类用法）；
        跨包广检索（想让 top_k 覆盖 k 个不同事件）时才置 True。

        reform=True（默认开）→ 先经「理解层 L1.5」把自然语言问句压成规范关键词，
        再做确定性匹配。三条取词路径，优先级从高到低：
          · keywords=（最优路径，AI 流）：AI 理解层先把 NL 解析成规范实体词列表
            直接传入，引擎零-ML 契约的落点；
          · decomposer=（可注入理解层）：传 callable 时调用它取关键词，引擎自身
            绝不调用任何模型；
          · 前两者皆无 → 退化到机械切分兜底 normalize_terms（按 [+\\s] 切分、strip
            标点、滤英文功能词），仅保证无 AI 接线时工具仍可用，不靠它硬顶召回与拒答。

        idf=True（默认开）→ 逐词计分乘以该词的 IDF 权重（稀有词权重高、常见
        词权重低），削弱 "the/when/did" 这类处处都有的功能词把判别词信号淹没。

        package_agg=False（默认关）→ 把同一事件包下所有锚点分数求和后只留
        每包一条（取包内得分最高锚点作代表）。用于「跨包广检索」时，让证据
        分散在多个锚点的包不被单段计分压低；与 dedup_packages 互斥（本模式
        已天然每包一条）。默认关闭是为了保留「同包多锚点精准召回」
        （Demo/OC 类单包多锚点用法）；跨包广检索（LoCoMo bench）显式开启。

        rerank=False（2026-08-27 起默认关）→ 若显式开启，在已捞到的候选上做一层
        确定性 BM25 重排（无向量、可由正文重建）。⚠️ 当前实现是【包级】BM25
        （按整文件建 token 桶，同包所有锚点共享同一分），非锚点级，对同包多锚点
        无法按锚点正文重排；且 2026-08-27 已移除原 OR-fail-safe / rule#1 两层
        「自以为是」保护层（用户判定冗余且引入 bug）。重开 rerank 前须先改锚点级。

        use_field_weights=True（V1.x 起默认开）→ 在以上排序之后，再叠加一层理解层
        四要素软加权（person/time/location/topic 一等字段族 + 包级 tags；详见
        《字段族与适配器契约》），并叠加查询→包确定性路由（见 hma.routing.resolve_scope：
        别名(唯一硬锁源) + 锚点关键词补齐(软) + 目录名/标题结构匹配(软)，以 DB package_id 为权威；
        confident(仅别名命中) 才硬锁候选池，否则退全库 + 伞包降权兜底）。
        命中要素越多越靠前，但**永不剔除候选**（只调序），故不构成对 HMA 零-ML
        纯文本检索契约的稀释——检索器本身仍从原始文本捞出候选，四要素只当「排序
        裁判」。要求候选包已写入一等字段族；未填字段族的旧包退化为纯 BM25（完全
        兼容）。传 False 可退回纯 BM25 排序。
        """
        if keywords is not None:
            # 真·功能接口：AI 理解层解析出的关键词直接传入（最优路径）。
            # 引擎零-ML——实体抽取/消歧由 AI 负责，引擎只做确定性检索与拒答；
            # 机械切分(normalize_terms) 仅在没有 AI 接线时的兜底，不靠它硬顶。
            # 归一小写：下游 _anchor_score / _apply_field_weights / _coverage /
            # _corpus_top_term_hit_files 全按小写匹配（锚点文本与四要素字段已
            # .lower()），AI 传入原大小写关键词会致子串匹配全失（如 "CEMA"
            # 命中不了小写 "cema" → 0 召回），故此处统一归一。
            terms = [str(k).lower() for k in keywords]
            ql = " ".join(terms) if terms else q.lower().strip()
        elif reform:
            if callable(decomposer):
                # 调用方注入的理解层（如 LLM 语义分解）。引擎零-ML：此路径由
                # agent shell 提供，引擎自身绝不调用任何模型。
                terms = decomposer(self, q, context=context) or []
            else:
                # 无 AI 接线 → 机械切分兜底（normalize_terms 按 +/空白 切词，
                # 非 CJK 二元；铁律：召回主路径只走 AI 流）。
                ql = q.lower().strip()
                terms = normalize_terms(ql)
            if terms:
                ql = " ".join(terms)
            else:
                ql = q.lower().strip()
                terms = normalize_terms(ql)
        else:
            ql = q.lower().strip()
            terms = normalize_terms(ql)
        if not terms:
            return []
        c = self._conn()
        pid = self.package_id if package_id is None else package_id
        # ② 检索策略：**全局先捞全 + 伞包降权**（自动路由只作软聚焦，从不硬锁）。
        # 自动路由 resolve_scope 返回 (scope_pid, confident)：
        #   - confident 恒为 False（关键词补齐 / 目录名·标题匹配都是软信号，泛词易碰撞）→
        #     **退全库检索**，由下游伞包降权兜底，谁都不预先排除（避免误锁把正确答案
        #     所在包直接砍掉）。关键词补齐是软信号（仅 +4 加权、绝不硬锁），因锚点
        #     keyword 含「检索/理解/ai」泛词，硬锁会灾难性误锁到 demo 等包。
        # 调用方显式 package_id / scope 永远硬过滤（尊重调用方界定的检索空间）。
        # 结构路由以 DB 真实 package_id 为权威（valid_pids）+ 锚点 keywords 派生
        # 的 kw_index 做内容级软聚焦，新包进仓库自动获得判别力（非手写打地鼠）。
        valid_pids = set(r[0] for r in c.execute(
            "SELECT DISTINCT package_id FROM events"))
        route_pid, route_conf = (
            routing.resolve_scope(q, self.root, valid_pids, self._kw_index())
            if (pid == "" and not scope) else (None, False))
        # confident 的自动路由才硬锁包；弱匹配退全库（避免错锁排除正解）。
        hard_pid = pid if pid != "" else (route_pid if route_conf else None)
        scl, spar = _scope_clause(scope, self.root)
        if hard_pid:
            # 兼容 query() 以文件名 stem 作包 id 的返回（如 'SCHEMA'）：
            # events.package_id 存的是目录相对路径（如 '项目/AIMH-design-journal'），
            # 故把 stem 解析为其所属文件的真实目录 package_id，使 scoped 检索能命中。
            # 若 scope_pid 本身已是目录 package_id，则 '.../<stem>.md' 不匹配任何行，
            # 保持原值，对既有调用方（MCP/CLI 传真实目录 id）零回归。
            chk = c.execute(
                "SELECT package_id FROM events "
                "WHERE REPLACE(filepath, '\\', '/') LIKE '%/' || ? || '.md' LIMIT 1",
                (hard_pid,)).fetchone()
            if chk:
                hard_pid = chk[0]
            # q-2（嵌套检索）/路由缩圈：范围搜"哲学"也命中"哲学/尼采"子树
            # 注：SELECT 列序 filepath,title,person,topic,location,anchors 须与
            # 下方 _four_variants(row[2:5]) 对应（person/topic/location 均为 dict 型
            # 四要素，规范名+变体并入锚点 atags，修 defect B）。
            sql = (
                "SELECT filepath,title,person,topic,location,anchors FROM events "
                "WHERE (package_id=? OR package_id LIKE ? || '/%')")
            params = [hard_pid, hard_pid]
            if scl:
                sql += " AND " + scl
                params += spar
            if getattr(self, "_blob_ok", False):
                bsql, bpar = self._blob_filter(terms, ql)
                if bsql:
                    sql += " AND " + bsql
                    params += bpar
            rows = c.execute(sql, params).fetchall()
        else:
            # 列序同 scoped 分支：filepath,title,person,topic,location,anchors
            sql = "SELECT filepath,title,person,topic,location,anchors FROM events"
            params = []
            conds = []
            if scl:
                conds.append("(" + scl + ")")
                params += spar
            if getattr(self, "_blob_ok", False):
                bsql, bpar = self._blob_filter(terms, ql)
                if bsql:
                    conds.append(bsql)
                    params += bpar
            if conds:
                sql += " WHERE " + " AND ".join(conds)
            rows = c.execute(sql, params).fetchall()
        if use_features:
            # F 段（features 精准集）：查询词命中 features 的 canonical/属性词 →
            # 把候选池缩到这些包；无命中则不缩（F 是额外集，缺失不影响 C+A）。
            fids = {h[0] for h in self.query_features(q, top_k=1000)}
            if fids:
                rows = [r for r in rows if r[0] in fids]
        # 包级四要素（person/topic/location）变体预展开：规范名 + 各变体都并入
        # 锚点可检索 tag 集，使「实体包按规范名/变体被召回」在锚点 BM25 层成立
        # （修 defect B：原 _score 的 atags 只取锚点级 keywords，包级 topic 的
        # 规范名「示例信物」躺在那儿却看不见，导致实体包 0 锚点命中、被示例角色
        # 包正文命中压顶）。仅扩打分用的 atags，不动展示字段；子串 OR 匹配与 FM
        # 语义一致（变体斜杠项整体入 tag，不在此拆 / ，拆 / 属 _feat_alt_match 职责）。
        _four_variant_cache = {}
        def _four_variants(row):
            key = (row[1], row[2], row[3], row[4]) if len(row) >= 5 else None
            if key is None:
                return []
            if key in _four_variant_cache:
                return _four_variant_cache[key]
            vs = []
            for col in row[2:5]:  # person, topic, location（均为 dict 型四要素）
                # DB 列存的是 JSON 字符串，需先 loads 成 dict（与 _apply_field_weights
                # 读四要素一致）；已是 dict 则直接用（防御兼容）。
                if isinstance(col, str):
                    try:
                        col = json.loads(col)
                    except Exception:
                        col = None
                if isinstance(col, dict):
                    for k, vals in col.items():
                        vs.append(str(k))
                        if isinstance(vals, list):
                            vs.extend(str(v) for v in vals)
                        elif vals is not None:
                            vs.append(str(vals))
            # topic 可能在第 5 列（取决于 SELECT 列序）；上方 2:5 已含 topic 当 dict
            low = [x.lower() for x in vs if x]
            _four_variant_cache[key] = low
            return low
        def _score(tlist):
            # idf 权重逐词预计算一次（置于 terms 循环外），避免逐锚点重复构造字典
            w = {t: (self._idf(t) if idf else 1.0) for t in tlist}
            out = []
            for row in rows:
                # SELECT 列序：filepath(0),title(1),person(2),topic(3),location(4),anchors(5)
                rid, doc_title, anchors_j = row[0], row[1], row[5]
                doc_title_l = (doc_title or "").lower()
                four = _four_variants(row)
                try:
                    anchors = json.loads(anchors_j or "[]")
                except Exception:
                    anchors = []
                for a in anchors:
                    if not isinstance(a, dict):
                        continue
                    # 文档标题注入锚点可检索文本（与 _bm25_corpus 同款）：让「仅由标题
                    # 区分」的文档能被标题词查询命中；仅影响打分用的 at，展示用锚点
                    # 标题（a.get("title"/"Chapter")）保持不变。
                    at = ((a.get("title") or a.get("Chapter") or "") + " " + doc_title_l).lower()
                    asum = (a.get("about") or a.get("summary") or "").lower()
                    atags = [t.lower() for t in (a.get("tags") or a.get("keywords") or [])]
                    atags = atags + four  # 并入包级四要素变体（defect B 修复）
                    abody = self._anchor_body(rid, a).lower()
                    s = _anchor_score(at, asum, atags, abody, ql, tlist, w)
                    if s > 0:
                        out.append((rid, a.get("title", "") or a.get("Chapter", ""),
                                    a.get("about", "") or a.get("summary", ""),
                                    a.get("locator", a.get("title", "") or a.get("Chapter", "")), s))
            return out

        scored = _score(terms)
        # 反伞包劫持（catch-all 降权）：「用户」包（用户数据）summary/锚点广提他包
        # 话题，全局检索时易压过正包置顶。除非查询显式含「用户/用户数据」，否则对其
        # 锚点降权——既保住「全局先捞全」的召回广度（T08/T12 类跨内容题不再被排除），
        # 又遏制伞包在话题查询里置顶（修 T02 的 no_hijack）。降权只调序、不剔除。
        _UMBRELLA = ("用户", "用户数据")
        if not any(tok in ql for tok in ("用户", "用户数据", "user")):
            scored = [(p, t, a, l, s * 0.3) if any(u in p for u in _UMBRELLA)
                      else (p, t, a, l, s) for (p, t, a, l, s) in scored]
        # 确定性排序：分数降序 → 包 id 升序 → 锚点标题升序。
        # 同分时不再依赖 SQLite 行序，同一查询恒返回同一结果（§13 无状态检索）。
        scored.sort(key=lambda x: (-x[4], x[0], x[1]))
        if package_agg:
            # 包级聚合（忠实复刻原型口径）：把同一事件包下所有锚点的
            # title/summary/body/tags 各自拼接成一个「虚拟块」，对块整体计一次分。
            # 这样每个 term 在包内只记一次贡献（不随锚点数线性放大），
            # 既不让「证据分散在多锚点」的包被单段计分压低，也不因包大而被高估。
            # 代表锚点取包内得分最高的一条，供展示/locator。已天然每包一条，
            # 故跳过随后的 dedup_packages。
            agg_list = []
            w = {t: (self._idf(t) if idf else 1.0) for t in terms}
            for rid, doc_title, anchors_j in rows:
                doc_title_l = (doc_title or "").lower()
                try:
                    anchors = json.loads(anchors_j or "[]")
                except Exception:
                    anchors = []
                if not anchors:
                    continue
                dict_anchors = [a for a in anchors if isinstance(a, dict)]
                # 文档标题注入虚拟块（与 _bm25_corpus / _score 同款）：使「仅由标题
                # 区分」的文档在包级聚合下也能被标题词查询命中。
                cat = ((doc_title_l + " ") + " ".join(
                    (a.get("title") or a.get("Chapter") or "") for a in dict_anchors)).lower()
                cas = " ".join((a.get("about") or a.get("summary") or "") for a in dict_anchors).lower()
                cab = " ".join(self._anchor_body(rid, a) for a in dict_anchors).lower()
                ctags = []
                for a in dict_anchors:
                    ctags.extend(t.lower() for t in (a.get("tags") or a.get("keywords") or []))
                s = _anchor_score(cat, cas, ctags, cab, ql, terms, w)
                if s <= 0:
                    continue
                rep = max(dict_anchors, key=lambda a: _anchor_score(
                    ((a.get("title") or a.get("Chapter") or "") + " " + doc_title_l).lower(),
                    (a.get("about") or a.get("summary") or "").lower(),
                    [t.lower() for t in (a.get("tags") or a.get("keywords") or [])],
                    self._anchor_body(rid, a).lower(), ql, terms, w))
                agg_list.append((rid, rep.get("title", "") or rep.get("Chapter", ""),
                                 rep.get("about", "") or rep.get("summary", ""),
                                 rep.get("locator", rep.get("title", "") or rep.get("Chapter", "")), s))
            scored = sorted(agg_list, key=lambda x: (-x[4], x[0], x[1]))
        if dedup_packages:
            seen, uniq = set(), []
            for r in scored:
                if r[0] in seen:
                    continue
                seen.add(r[0])
                uniq.append(r)
            scored = uniq
        if rerank:
            rerank_sorted = self._rerank(scored, ql, pid)
            scored = rerank_sorted[:top_k]
        if use_field_weights:
            scored = self._apply_field_weights(
                scored, q, terms, route_target=(route_pid if route_conf else None))
        # ★ 相关性硬阈值过滤：IDF 加权匹配分低于 θ 的结果视为不相关丢弃，
        # 治 corpus_missing_entity ANY-match 漏拒（通用词命中即放行吐噪声）。
        if allow_abstain and terms:
            scored = self._relevance_filter(scored, terms, theta=0.5)
        # 对外返回：把内部用的 filepath 主键转回文件名 stem（保持历史契约，
        # 基准/bench 以 stem 做断言），内部 _pkg_fields/_pkg_body 仍用 filepath。
        _stemify = lambda t: (os.path.splitext(os.path.basename(t[0]))[0],) + t[1:]
        if allow_abstain:
            # entity_gate：仅当 terms 来自 AI 接口(keywords/decomposer) 时，
            # 才启用『稀有实体全缺失→硬拒答』反相闸（机械拆词不可靠，见 _abstain）。
            ai_mode = keywords is not None or callable(decomposer)
            res = self._abstain(scored, q, terms, top_k,
                                 kappa if kappa is not None else ABSTAIN_KAPPA,
                                 pid, entity_gate=ai_mode)
            ans = [_stemify(r) for r in res["answer"]]
            res["answer"] = ans
            return res
        return [_stemify(r) for r in scored[:top_k]]

    def _apply_field_weights(self, scored, q, terms, route_target=None):
        """理解层四要素软加权 + 查询→包路由（post-retrieval rerank，零 ML）。

        对每条候选按「命中的结构化要素数」加权（时间/地点/人物/主题四要素 +
        包级 tags），命中越多越靠前，但**本函数内不剔除任何候选**——只调序。语义是
        「结构化约束缩小候选 + 文本精排」的软版：检索器本身仍从原始文本捞出候选，
        四要素只当「排序裁判」，故不构成对 HMA 零-ML 纯文本检索契约的稀释。
        （注：本函数不剔除 ≠ 整条管线不剔除；query_anchors 在调用本函数之后仍可能
        经 _relevance_filter 做相关性阈值剔除——那是独立关卡，非本函数职责。）

        修复（此前 topic 一等字段被解包却从未使用，W_TOP 错打在 summary+锚点文本
        重叠上）：现在 topic 字段与包级 tags 都参与匹配（子串口径，因 tags 形如
        "存储架构"、查询 term 是 "架构"，集合交集会漏，故用子串）。design-journal
        的判别信号恰在 tags（aimh/architecture/四要素/存储架构…），用户包的判别信号
        在 topic（用户画像/学历/大专/求职…）——两者现在都被真正纳入排序。

        ② 查询→包路由：route_target（由 query_anchors 经干净信号算出）非 None 时，
        对该目标包锚点加判（mc+?), 并加重奖励，把跨包概念共现导致的「错包置顶」
        纠正回正确包，且仍零-ML、可解释、不剔除。

        主排序 = 命中要素数(降序)；次 = 加权 bonus(降序)；tiebreak = 原 BM25 分(降序)。
        """
        if not scored:
            return scored
        ql = str(q).lower()
        toks = re.findall(r"[A-Za-z0-9]+|[一-鿿]+", ql)
        locs = {t for t in toks if t in _LOC_WORDS}
        terms_set = set(terms)
        W_P, W_T, W_TOP, W_L = _FIELD_W

        rids = sorted({r[0] for r in scored})
        c = self._conn()
        # rid 即 events.filepath（完整路径：query_anchors 的候选行直接取自 filepath 列），
        # 故用 WHERE filepath IN (rids) 在 SQL 侧直接缩到候选包——O(候选) 而非 O(全库)，
        # 并顺带修复旧版「stem∈rid_set 恒不匹配」导致四要素加权永不生效的死代码。
        # 额外取 package_id（路由目标判定）与 tags（design-journal 判别信号）。
        placeholders = ",".join("?" * len(rids))
        rows = c.execute(
            "SELECT filepath,package_id,person,event_date,location,topic,tags,"
            "summary,anchors FROM events WHERE filepath IN (%s)" % placeholders,
            rids).fetchall()
        # 相对时间（"90 天前"）的锚点 = 候选里最新的事件日期，即系统自知的「现在」。
        newest = max((r[3] or "" for r in rows), default="")
        hint = parse_time_hint(ql, newest or None)

        pkg = {}
        for rid, pkg_id, person_j, edate, loc_j, topic_j, tags_j, summ, anc_j in rows:
            person_set = {p.lower() for p in _flat_variants(person_j)}
            tlevel = hint.match(edate)
            loc_set = {l.lower() for l in _flat_variants(loc_j)}
            topic_set = {t.lower() for t in _flat_variants(topic_j)}
            tags_set = {t.lower() for t in _flat_variants(tags_j)}
            # topic + tags 用子串口径拼接（tags 如"存储架构"需让"架构"命中）
            field_text = " ".join(topic_set | tags_set).lower()
            text_l = (summ or "").lower()
            try:
                for a in json.loads(anc_j or "[]"):
                    text_l += " " + (a.get("title") or a.get("Chapter") or "") + " " + \
                              (a.get("about") or a.get("summary") or "") + " " + self._anchor_body(rid, a)
            except Exception:
                pass
            pkg[rid] = (person_set, tlevel, loc_set, field_text, pkg_id)

        # 「名称比对」（人名消歧，软加权非剔除）：把【候选行】的 person 词表归一，
        # 再解析查询指代的人名；精确全名命中→boost，同姓异人→penalty。
        # 仅在查询能解析到已知人名时才启用比对/惩罚；否则退回原 token 重叠逻辑。
        # 词表从已抓取的候选行构建，省去一次全库 DISTINCT 扫描（O(N)→O(候选)）；
        # 字段加权只作用于候选，全局词表非必需——查询人名解析落空时退回 token 重叠逻辑。
        person_vocab_norm = set()
        for r in rows:
            for v in _flat_variants(r[2]):
                if v:
                    person_vocab_norm.add(_norm_name(v))
        q_norm = _norm_name(ql)
        resolved_person = q_norm if q_norm in person_vocab_norm else None

        out = []
        for (rid, atitle, asum, loc, s) in scored:
            ps, tlevel, ls, field_text, pkg_id = pkg.get(rid, (set(), 0, set(), "", ""))
            ps_norm = {_norm_name(p) for p in ps}
            if resolved_person is not None:
                # 查询已解析到已知人名：精确全名命中=boost，同姓异人=penalty（软加权，不剔除）
                exact = resolved_person in ps_norm
                shared = (not exact) and any(_share_surname(pn, resolved_person) for pn in ps_norm)
                p_hit = exact                       # 仅精确全名算「命中要素」
                p_bonus = W_P if exact else (-W_P if shared else 0)
            else:
                # 查询未解析到已知人名：退回原 token 重叠逻辑（兼容非人名查询）
                p_hit = len(terms_set & ps) > 0
                p_bonus = W_P if p_hit else 0
            # topic 字段 + 包级 tags 命中（修复 topic 死字段；tags 是 design-journal 判别信号）。
            # 命中口径：ascii 词要求整词精确(防 corpus_missing⊂corpus_missing_entity 子串误判
            # 把无关包整包顶起)；CJK 词允许子串(架构⊂存储架构 属期望命中)。
            field_tokens = topic_set | tags_set
            t_hit = any(_field_term_hit(term, field_tokens) for term in terms_set)
            l = any(loc in field_text for loc in locs)
            mc = (1 if p_hit else 0) + (1 if tlevel else 0) + (1 if t_hit else 0) + (1 if l else 0)
            bonus = p_bonus + W_T * tlevel + W_TOP * (1 if t_hit else 0) + W_L * (1 if l else 0)
            # ② 路由奖励：本锚点所属包命中查询路由目标 → 加判并加重奖励
            if route_target and route_target in (pkg_id or ""):
                mc += 1
                bonus += C.FIELD_ROUTE_BONUS
            # ★ 字段加权改为【封顶加法折进 score】，相关性回归主排序：
            # 原 (-mc,-bonus,-score) 让"包级命中要素数"压过"文本相关度"，整包(含无关 daylog)
            # 凭 topic/tags 子串被顶到真答案前(T11/T08/T03)。现把字段贡献折成
            # rank_score = s + min(bonus+mc*_FIELD_NUDGE, s*_FIELD_CAP) 再排序——
            # 字段只作有上限的轻推，不再能颠覆数倍更高的文本分。
            field_influence = bonus + mc * _FIELD_NUDGE
            rank_score = s + min(field_influence, s * _FIELD_CAP)
            out.append((rid, atitle, asum, loc, s, rank_score))
        out.sort(key=lambda x: (-x[5], x[0], x[1]))
        return [(r[0], r[1], r[2], r[3], r[4]) for r in out]

    def query_features(self, q, top_k=5, min_hit=2):
        """零-ML 特征重叠匹配器（理解层 L1.5）。

        实体以 {canonical: [属性特征]} 登记在 features 字段。召回逻辑：
          - canonical 整词命中查询 → 强命中（reason='canonical'）；
          - 特征整串命中查询 → 强信号（reason='feature_exact'，score 同档，
            不受 min_hit 限制：用户直接问某属性特征词时也须浮出）；
          - 否则 query 的 CJK 字与某实体的特征集重叠数 ≥ min_hit → 浮出候选
            （reason='feature'，score=重叠数）。
        浮出的是候选集（可能多个实体），残余歧义现由 Memory.resolve_query 承担
        （B 类 resolver 已落地：歧义门 + 特征判别澄清 + 负特征对偶），本方法只做召回增强，
        不替代消歧。

        V2：features 列已并入四要素 dict（person/topic/location 的
        {canonical:[变体]}），故改为扫描这三个字段、合并成 fmap 后与旧逻辑等价。
        """
        qc = set(re.findall(r"[一-鿿]", q or ""))
        c = self._conn()
        rows = c.execute(
            "SELECT filepath, person, topic, location FROM events").fetchall()
        hits = []
        for pid, pj, tj, lj in rows:
            fmap = {}
            for fj in (pj, tj, lj):
                try:
                    d = json.loads(fj) if fj else {}
                except Exception:
                    d = {}
                if not isinstance(d, dict):
                    continue
                for canon, feats in d.items():
                    fmap.setdefault(canon, [])
                    fmap[canon].extend(feats or [])
            if not fmap:
                continue
            for canon, feats in fmap.items():
                if q and canon in q:
                    hits.append((pid, canon, "canonical", len(qc) + 10))
                    break  # 本包已有强命中，停止扫其余实体
                # 特征整串命中查询 → 强信号（等同 canonical 级别的精准召回），
                # 不受 min_hit 限制：用户直接问某个属性特征词（如「重生计划」
                # 「武器重构」）时，该特征整串出现在查询里已是强证据，必须浮出，
                # 否则单特征命中 count=1 < min_hit 会被漏掉（F-stage 启用必需）。
                if any(_feat_alt_match(f, q) for f in (feats or [])):
                    hits.append((pid, canon, "feature_exact", len(qc) + 5))
                    continue
                hit = sum(1 for f in (feats or []) if f and _feat_alt_match(f, q))
                if hit >= min_hit:
                    hits.append((pid, canon, "feature", hit))
        hits.sort(key=lambda x: -x[3])
        return hits[:top_k]

    def recall_multihop(self, q, top_k=5, max_hops=2, package_id=None,
                        keywords=None, decomposer=None):
        """沿 linked 双向 BFS 扩簇的多跳召回（V1.0 生产化，此前仅文档设想）。

        跳1：query_anchors(q) 取单跳种子包（anchor 级命中，filepath 作邻接键）；
        跳2：从每种子沿 linked 边 BFS，扩到 max_hops 内的可达簇 C(e)；
        对簇内每个包用 query_anchors(q, package_id=该包) 取最佳锚点分，按
        (hop, -score) 排序返回包级命中 [(rid, title, summary, score), ...]。

        语义对齐设计文档 §8：多跳把「实体」换成「簇」，扩簇并入更多边缘特征→
        重叠区变大→更易歧义，故多跳召回增强**不能跳过歧义门**：调用方应走
        resolve_query(multihop=True)，把扩簇结果喂给既有实体歧义门（机制复用）。
        零 ML、可由 index.db 重建、幂等（同查询恒返回同结果）。
        """
        seeds = self.query_anchors(q, top_k=20, allow_abstain=False,
                                   package_id=package_id,
                                   keywords=keywords, decomposer=decomposer)
        if not seeds:
            return []
        c = self._conn()

        def _rid_to_fp(rid):
            # query_anchors / query 返回的 element[0] 是文件名 stem，邻接表键是
            # filepath —— 这里把 stem 解析回 filepath。Windows 上 filepath 存反斜杠，
            # 用 REPLACE 归一后再做 suffix LIKE（避免 '/' 匹配不到 '\'）。
            row = c.execute(
                "SELECT filepath FROM events WHERE REPLACE(filepath, '\\', '/') LIKE ?",
                ("%/" + rid + ".md",)).fetchone()
            return row[0] if row else None

        def _named_hit(n_q, n_rid, n_title):
            """查询点名包判定：查询与候选的双向 4+gram 滑动子串互查（容忍 检索/召回
            首字变体）。

            关键：必须用【滑动 4-gram】而非「整段 CJK 当一 token」——后者把
            "检索消歧管线设计和数学思路文档怎么互链" 当成一个 15 字 token，永远不可能是
            候选名（"召回消歧管线设计"）的子串 → 永不命中。滑动 4-gram 让公共片段
            "消歧管线设计"/"数学思路" 被彼此捕获，且只加分不播种的旧逻辑改为「播种+
            加分」双管齐下（不可达包也能进 BFS）。
            """
            def _grams(s):
                out = set()
                for run in re.findall(r"[一-鿿]+", s):
                    L = len(run)
                    for k in range(4, L + 1):
                        for i in range(0, L - k + 1):
                            out.add(run[i:i + k])
                for w in re.findall(r"[a-z0-9]{4,}", s):
                    out.add(w)
                return out
            cand = n_rid + " " + n_title
            qg, cg = _grams(n_q), _grams(cand)
            return any(g in cand for g in qg) or any(g in n_q for g in cg)

        seed_fps = set()
        for s in seeds:
            fp = _rid_to_fp(s[0])
            if fp:
                seed_fps.add(fp)
        # 也把包级单跳命中（query）当种子：无锚点但 title/summary 命中的包也能扩簇
        for rid, *_ in self.query(q, top_k=20, package_id=package_id,
                                  keywords=keywords, decomposer=decomposer):
            fp = _rid_to_fp(rid)
            if fp:
                seed_fps.add(fp)
        # 命名实体播种（治本）：查询点名的包（如「X 和 Y 怎么互链」中的 X/Y）即便
        # BM25 未进 top-20 也必须作为种子，否则 BFS 永远到不了答案包。原 named-boost
        # 只加分不播种 → 不可达包永远沉底。匹配用 4+gram 子串互查，容忍 检索/召回
        # 等首字变体（查询写「检索消歧」、真实包名「召回消歧」仍命中）。
        n_q = re.sub(r"[\s\-_]", "", str(q)).lower()
        for fp, title in c.execute("SELECT filepath, title FROM events").fetchall():
            rid = os.path.splitext(os.path.basename(fp))[0]
            if _named_hit(n_q,
                          re.sub(r"[\s\-_]", "", rid).lower(),
                          re.sub(r"[\s\-_]", "", (title or "")).lower()):
                seed_fps.add(fp)
        if not seed_fps:
            return []
        # 确定性：种子按 filepath 排序，避免 set 迭代顺序随进程哈希随机化（G6 多跳
        # 跨 run 结果漂移的根因——同 hop 并列时输出序依赖插入序）。
        seed_fps = sorted(seed_fps)
        adj = self._linked_adjacency()
        # BFS：从每种子（已解析为 filepath）扩到 max_hops 内可达包，记录最小跳数。
        # 邻居按 filepath 排序展开 → 最短跳数确定 + 插入序确定（dist 值本身是最短
        # 路径已确定，插入序仅影响同 hop 并列时的输出序，须确定性）。
        dist = {}
        for sf in seed_fps:
            if sf in dist:
                continue
            dist[sf] = 0
            stack = [(sf, 0)]
            while stack:
                node, h = stack.pop()
                for nb in sorted(adj.get(node, ())):
                    if nb not in dist or h + 1 < dist[nb]:
                        dist[nb] = h + 1
                        if h + 1 < max_hops:
                            stack.append((nb, h + 1))
        # 每种子包的最佳命中分（link-boost：被强种子**直接链接**的目标包应浮到
        # 前面——"X 和 Y 怎么互链"的答案恰是种子包的链接邻居，不该被无关 hop-0
        # 关键词命中包压在 top-5 之外）。
        seed_score = {}
        for s in seeds:
            fp = _rid_to_fp(s[0])
            if fp:
                seed_score[fp] = max(seed_score.get(fp, 0.0), s[4])
        c = self._conn()
        seen = set()
        out = []
        for fp, hop in sorted(dist.items(), key=lambda x: (x[1], x[0])):
            row = c.execute(
                "SELECT package_id, title, summary FROM events WHERE filepath=?",
                (fp,)).fetchone()
            if not row:
                continue
            pkgid, title, summary = row
            rid = os.path.splitext(os.path.basename(fp))[0]
            if rid in seen:                     # 包级去重（同包多锚点只留一条）
                continue
            seen.add(rid)
            hits = self.query_anchors(q, top_k=1, allow_abstain=False,
                                      package_id=pkgid,
                                      keywords=keywords, decomposer=decomposer)
            own = hits[0][4] if hits else 0
            # link-boost：直接相邻 seed 的最高分（无则 0）
            link = max((seed_score.get(nb, 0.0) for nb in adj.get(fp, ())),
                       default=0.0)
            score = max(own, link)
            # 命名实体 boost：「X 和 Y 怎么互链」类查询通常点名 X/Y 包，被点名包
            # 即为答案候选 → 强提权（零-ML、可解释），破解 BM25 跨包饱和导致的
            # 并列压底（SCHEMA/front-matter字段规则-v2/数学思路 等正确答案）。
            n_rid = re.sub(r"[\s\-_]", "", rid).lower()
            n_title = re.sub(r"[\s\-_]", "", (title or "")).lower()
            named = _named_hit(n_q, n_rid, n_title)
            if named:
                score += C.NAMED_LINK_BOOST
            out.append((rid, title, summary, score, hop))
        # 排序：链接相关度（final score，含命名 boost）优先，hop 仅作 tiebreak，
        # 末位用 rid 字符串兜底 → 完全确定（消除 run-to-run 漂移）。
        out.sort(key=lambda x: (-x[3], x[4], x[0]))
        return [(r[0], r[1], r[2], r[3]) for r in out[:top_k]]

    @staticmethod
    def _score(ql, rid, title, summary, person_aliases, other_aliases, tags, anchor_aliases=None):
        # 覆盖度模型（修包级累加 bug）：
        # 同一查询词在本包多字段（title/alias/tag/summary）只取【最高命中档】加一次，
        # 不再逐字段累加，避免长/多字段文档靠堆词虚高（如「主义」二元碎片在四字段各加一次）。
        # person alias 精确匹配高杠杆（PKG_PERSON_ALIAS_EXACT=BASE_UNIT×1.0×1.0=150，
        # 高于 PKG_TITLE_SUBSTR=BASE_UNIT×0.8×0.4=48），落实「常用名优先」。
        # 注：注释原写 200/60 系 BASE_UNIT=200 时代遗留，BASE 改 150 后已同步常量、此注释一并更正。
        # 垃圾二元（_is_garbage_bigram）只给极小分，不靠命中数虚高。
        terms = normalize_terms(ql)
        if not terms:
            return 0
        rid_l = rid.lower()
        title_l = (title or "").lower()
        sum_l = (summary or "").lower()
        tags_l = [t.lower() for t in tags]
        p_al = [a.lower() for a in person_aliases]
        o_al = [a.lower() for a in other_aliases]
        a_al = [x.lower() for x in (anchor_aliases or [])]

        s = 0
        # id 命中（单包单次，不随词循环）
        if ql == rid_l:
            s += C.PKG_ID_EXACT
        elif any(t in rid_l for t in terms):
            s += C.PKG_ID_SUBSTR
        # 逐词：每词在本包所有字段取最高档一次性加（不累加）
        for t in terms:
            best = 0
            # person alias（高杠杆）
            if any(t == al for al in p_al):
                best = max(best, C.PKG_PERSON_ALIAS_EXACT)
            elif any(t in al for al in p_al):
                best = max(best, C.PKG_PERSON_ALIAS_SUBSTR)
            # 其他 alias（topic/location）
            if any(t == al for al in o_al):
                best = max(best, C.PKG_OTHER_ALIAS_EXACT)
            elif any(t in al for al in o_al):
                best = max(best, C.PKG_OTHER_ALIAS_SUBSTR)
            # 锚点 keyword 独立档（B 方案：不再蹭 proper-noun EXACT 150，治本锚点 keyword 污染包级聚合）
            if any(t == al for al in a_al):
                best = max(best, C.PKG_ANCHOR_KW_EXACT)
            elif any(t in al for al in a_al):
                best = max(best, C.PKG_ANCHOR_KW_SUBSTR)
            # title 命中
            if any(t in title_l for t in terms):
                best = max(best, C.PKG_TITLE_SUBSTR)
            # tag 命中（exact 优先：真主题 tag 压过偶提锚点词；治本 coherence）
            if any(t == tg for tg in tags_l):
                best = max(best, C.PKG_TAG_EXACT)
            elif any(t in tg for tg in tags_l):
                best = max(best, C.PKG_TAG_SUBSTR)
            # summary 命中
            if any(t in sum_l for t in terms):
                best = max(best, C.PKG_SUMMARY_SUBSTR)
            # 垃圾二元只给极小分
            if _is_garbage_bigram(t):
                best = min(best, C.PKG_GARBAGE_BIGRAM) if best else C.PKG_GARBAGE_BIGRAM
            s += best
        # 静态分类惩罚（trivial 少注入），非热度/新鲜度
        if "trivial" in tags_l:
            s -= C.PKG_TRIVIAL_PENALTY
        return s

    # ---- 两层导航 resolver（网页/CLI 共用的 core 能力）----------------------
    def resolve_two_layer(self, q, top_k=10, scope=None):
        """两层导航 resolver：关键词 -> L1 目录(package_id) -> 锁目录内 L2 md 文件(title)。

        定级复用本类 @staticmethod _score（与 query() 同款），不手搓权重。
        唯一才锁，>=2 才触发歧义门反问，绝不猜测/捞取/替用户挑。
        多关键词带覆盖率闸门（所有词都命中该目录才候选），防跨主题误锁。
        返回四态信封 {stage: zero/dir/file/hit, dirs, files, hit, results}。
        scope=某 package_id 时跳过 L1，直接在该目录内解析 L2（下钻）。
        """
        if not q or not q.strip():
            return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}
        terms = [t.strip() for t in re.split(r"[\s,，]+", q.strip()) if t.strip()]
        if not terms:
            return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}

        cx = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            rows = cx.execute(
                "SELECT filepath, package_id, title, summary, person, topic, location, tags, anchors "
                "FROM events"
            ).fetchall()
        finally:
            cx.close()
        if not rows:
            return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}

        def flat(jstr):
            try:
                return _flat_variants(jstr)
            except Exception:
                try:
                    d = json.loads(jstr) if jstr else {}
                except Exception:
                    d = {}
                if isinstance(d, dict):
                    out = []
                    for k, vs in d.items():
                        out.append(str(k))
                        out.extend(str(v) for v in (vs or []))
                    return out
                return []

        # 每 term 文件级真实 _score 命中
        term_dir_best, term_dir_files = {}, {}
        for t in terms:
            ql = t.lower().strip()
            tb, tf = {}, {}
            for fp, pid, title, summary, pj, tj, lj, tags_j, aj in rows:
                rid = os.path.splitext(os.path.basename(fp))[0]
                person_aliases = flat(pj)
                other_aliases = flat(tj) + flat(lj)
                # B 方案：锚点 keyword 分离到独立 anchor_kw 档（不再蹭 proper-noun EXACT 150）；
                # Chapter 仍进 other_aliases（topic 通道，原行为保留）。
                anchor_kw = []
                try:
                    for a in (json.loads(aj) if aj else []):
                        if isinstance(a, dict):
                            other_aliases.append(str(a.get("Chapter") or ""))
                            anchor_kw.extend(str(k) for k in (a.get("keywords") or []))
                except Exception:
                    pass
                try:
                    tags = json.loads(tags_j) if tags_j else []
                except Exception:
                    tags = []
                s = self._score(ql, rid, title, summary, person_aliases, other_aliases, tags, anchor_kw)
                if s > 0:
                    if pid not in tb or s > tb[pid]:
                        tb[pid] = s
                    tf.setdefault(pid, []).append((rid, title, summary, s, fp))
            term_dir_best[t], term_dir_files[t] = tb, tf

        def aggregate_dir(pid):
            seen = {}
            for t in terms:
                for (rid, title, summary, s, fp) in term_dir_files.get(t, {}).get(pid, []):
                    if fp not in seen or s > seen[fp][3]:
                        seen[fp] = (rid, title, summary, s, fp)
            return sorted(seen.values(), key=lambda x: -x[3])

        if scope:
            # L1 已锁（下钻）：直接解 L2
            f_in = aggregate_dir(scope)
            if not f_in:
                return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}
            if len(f_in) >= 2:
                fc = [{"package_id": scope, "title": r[1], "filepath": r[4],
                       "summary": r[2], "score": round(float(r[3]), 2)} for r in f_in]
                return {"stage": "file", "dirs": [], "files": fc, "hit": None, "results": fc}
            h = f_in[0]
            hit = {"package_id": scope, "title": h[1], "filepath": h[4],
                   "summary": h[2], "score": round(float(h[3]), 2)}
            return {"stage": "hit", "dirs": [], "files": [], "hit": hit, "results": [hit]}

        # L1 目录聚合 + 覆盖率闸门（所有 term 都命中该目录才候选，防跨主题误锁）
        dir_best, dir_files = {}, {}
        all_pids = {pid for (_, pid, *_rest) in rows}
        for pid in all_pids:
            hit_terms = [t for t in terms if pid in term_dir_best.get(t, {})]
            if len(hit_terms) < len(terms):
                continue
            dir_best[pid] = max(term_dir_best[t][pid] for t in hit_terms)
            dir_files[pid] = aggregate_dir(pid)

        if not dir_best:
            return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}

        dir_ranked = sorted(dir_best.items(), key=lambda x: -x[1])
        # dK 瀑布裁切：砍掉分差 > CUTOFF_GAP_FLOOR 的远低噪声包
        # （如"示例事件"里示例信物包 18 分、示例角色包 150 分 → 砍示例信物，只留示例角色）
        cut = ro.waterfall_cut([(p, "", "", "", s) for p, s in dir_ranked], C.CUTOFF_GAP_FLOOR)
        kept = [e[0] for e in cut]
        if len(kept) == 1:
            top_dirs = kept
        else:
            # 并列：优先 package title 含查询词的家包（解决"2包只有1对"）
            tl = [t.lower() for t in terms]
            title_match = [p for p in kept if any(t in p.split("/")[-1].lower() for t in tl)]
            top_dirs = title_match if len(title_match) == 1 else kept
        if len(top_dirs) >= 2:
            cands = []
            for p in top_dirs:
                files = dir_files[p]
                titles = []
                for (_, t, _, _, _) in files:
                    if t not in titles:
                        titles.append(t)
                cands.append({"package_id": p, "title": files[0][1] if files else p,
                              "score": round(float(dir_best[p]), 2), "files": titles[:8]})
            return {"stage": "dir", "dirs": cands, "files": [], "hit": None, "results": cands}

        locked = top_dirs[0]
        f_in = dir_files[locked]
        if len(f_in) >= 2:
            fc = [{"package_id": locked, "title": r[1], "filepath": r[4],
                   "summary": r[2], "score": round(float(r[3]), 2)} for r in f_in]
            return {"stage": "file", "dirs": [], "files": fc, "hit": None, "results": fc}
        h = f_in[0]
        hit = {"package_id": locked, "title": h[1], "filepath": h[4],
               "summary": h[2], "score": round(float(h[3]), 2)}
        return {"stage": "hit", "dirs": [], "files": [], "hit": hit, "results": [hit]}
