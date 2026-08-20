"""AIMH 机械执行层（拒答 + 理解链路的确定性实现）。

本模块从 hma_core 抽出，是 CEMA「Agent 即理解层」里**机械**那一半：
所有零-ML、确定性可重建的查询理解 / 相关性过滤 / 四道拒答闸 /
语料包含性判定都在此。hma_core.Memory 通过继承 MechanicalMixin 复用，
AI 接口钩子（keywords / decomposer / entity_gate）仍留在 hma_core，
以保持「理解层可注入 LLM 回调」的能力，机械层只认确定性默认实现。
"""
import os
import re
import json

# 拒答层机械兜底闸用：查询与语料零共现 → 域外语料 → 拒答（惰性导入，避免加载期耦合）。
from .refine import corpus_overlap_absent


# 剥词首尾标点用。只剥两端，不动词内分隔符，
# 因此 "维罗妮卡·夏·雪莱" 保持完整，而 "group?" 归一为 "group"。
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

def normalize_terms(ql):
    """把查询串切成用于匹配的 term 列表。

    1. 按空白切分；剥去每个 term 首尾标点。
    2. 滤掉英文功能词；若全被滤空则退回未过滤结果
       （保证 "the" 这类查询本身仍可检索）。
    3. 中文无空格 → 整句为单个 term，停用词表纯 ASCII 故不受影响。
    """
    raw = [t.strip(_PUNCT) for t in re.split(r"\s+", ql)]
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

# 查询改写用的停用词（与 locomo_bench.reform 的 STOP 逐字一致，保证
# 内建 reform 与 bench 的 reform 行为等价，避免多删 having/doing 等词
# 导致召回回归）。故意用 bench 那套（_STOPWORDS 的超集会多删词、伤召回）。
_REFORM_STOP = frozenset("""
a an the is are was were be been being do did does done to of in on at for
with and or but that this these those what when where who whom whose which why how
he she it they we you i my your his her their our its me him them us as have has had
will would can could should may might must about from by into onto over under not no
yes if then so because there here out up down off very just also any all each every
both such own same than too only
""".split())

def _reform_terms(ql):
    """理解层查询改写的确定性内建版（query_anchors 默认开启）。

    在 normalize_terms 去停用词之上，进一步把自然语言问句压成有判别力的
    关键词串；无模型、可由正文重建，对应 HMA 理解层/L2 的「查询分解」职责。
    等价于 locomo_bench.reform()，但做了 CJK 安全处理：

      - 英文：丢弃长度<3 且不含数字的短噪词（go/up/ai/ny…），保留判别词。
      - 中文：按「连续汉字成词」整词保留；单/双字中文（夏 / 雪莱）不会被
        长度规则误删，故对 Veronica/OC 等中文场景安全。

    返回用于匹配的 term 列表；若全被滤空则返回原文分词（保证可检索）。
    """
    toks = re.findall(r"[A-Za-z0-9]+|[一-鿿]+", str(ql).lower())
    out = []
    for t in toks:
        if re.search(r"[一-鿿]", t):
            out.append(t)                       # 中文整词保留（短词/专名直接匹配）
            # 零-ML 中文分词兜底：长中文串做二元滑动窗口，
            # 让"用户的学历是什么"能拆出"学历"去匹配锚点 about/正文——
            # 纯 CJK 运行无词边界，不切就整串当唯一 term，自然问句全失配。
            if len(t) > 2:
                for i in range(len(t) - 1):
                    bg = t[i:i + 2]
                    if bg not in out:
                        out.append(bg)
        elif t not in _REFORM_STOP and (len(t) >= 3 or re.search(r"\d", t)):
            out.append(t)                       # 英文：去短噪词
    return out or [t.strip(_PUNCT) for t in re.split(r"\s+", str(ql).lower()) if t.strip(_PUNCT)]

# 关键词比对加分权重（用户提议“比对到后对这个关键词加权”，模块级常量供 _anchor_score 使用）：
# 查询里的每个关键词一旦在本文块命中，即加固定大分——查询词即用户意图信号，
# 命中即重赏，让“匹配上用户原话关键词”的包压倒性靠前。不依赖 idf 压缩下的稀有度，
# 故在小索引（稀有词 idf 被 +1 地板压扁）也能靠“命中用户原词”翻盘。
_KW_FIXED = 200.0  # 关键词「覆盖度」奖励：查询词只要被本锚点覆盖（命中≥1 个真实词）即一次性 +200，不再按命中数量 ×N——避免长/无关文档靠堆词虚高（逐词子串命中已在上方 at/asum/abody 按词数区分）

# 二元噪声词固定奖励（远小于 _KW_FIXED）：滑动窗口生成的垃圾二元（是设/计过/过一…）
# 命中只给极小固定分，避免它们靠"命中数多"虚高长文档、压住真正用户关键词包。
_KW_BIGRAM_BONUS = 10.0

# 零-ML 中文二元噪声判定：长中文串被滑成所有相邻二元，其中含语法/代词/否定/数词/
# 指代/助词/介词字符的（我是/是不/不是/是设/计过/过一/一个/个角…）视为噪声二元，
# 只拿 _KW_BIGRAM_BONUS 极小固定分；内容二元（用户/角色/设计/武器/重构…）不受影响、拿满 _KW_FIXED。
_GARBAGE_FUNC = set("的了吗呢吧啊呀嘛咯是的不没我你他她它咱们这那哪些个之与和或但而也把被让给对从向在到过着地得一二三四五六七八九十百千万什怎怎么忆几哪能可很最")

def _is_garbage_bigram(t):
    return len(t) == 2 and (t[0] in _GARBAGE_FUNC or t[1] in _GARBAGE_FUNC)

# grounding 过注入抑制（反向操作）：四要素/tags 接地展开出的检索词，若跨「≥此包数」
# 的包出现，视为跨包常见词（非判别信号），不再注入成查询词。即「越多包出现的词越
# 不值得当检索词，越少包出现的稀有词才保留作判别」——修 T05/T07 因用户画像包把
# OC 实体/泛词当「产出作品」变体整批注入、把 veronica-origin 顶上 TOP 的共现陷阱。
# 门限取小整数（非比例），因小索引下稀有判别词也常只落 1–2 包；3≈9% 的包即算跨包常见。
_GROUND_PKG_GATE = 3

# 拒答层默认阈值（在 Veronica mini-bench / LoCoMo cat5 上离线校准，不靠拍脑袋）
ABSTAIN_KAPPA = 0.34    # Gate1：top 锚点 IDF 加权覆盖度 < 此值 → 拒答

ABSTAIN_HIGH_K = 0.67   # 覆盖度 ≥ 此值 → confidence=high，否则 low

ABSTAIN_DEFAULT_MSG = ("未查询到与查询词相关的记忆内容。请判断：是查询表述过窄/模糊"
                       "需要进一步向用户澄清，还是确无相关内容应明确告知用户。")

class MechanicalMixin:
    """拒答 + 理解链路的确定性方法集合，由 hma_core.Memory 继承。"""

    def _understand_query(self, q, context=None):
        """理解层 L1.5（确定性默认实现，零-ML）：把自然语言问句压成规范关键词。

        对应 HMA「Agent 即理解层」的读时契约——引擎只认空格分词的中文关键词，
        NL 问句的中文分解由理解层做最小必要性抽取。本默认实现分两步合成：

          1. 四要素 grounding：拿问句(含 context)去匹配本仓已知 person/topic/
             event_date/location 的「规范名 + 变体」，命中即把【规范名】当检索词
             （用户用变体提问也能接地回规范名，如「小维」→「维罗妮卡」）。
          2. 内容词兜底：用 _reform_terms 的 CJK 二元 + 英文去噪，捞取未落入
             四要素词表的判别内容词（如「学历」「宝石」）。

        两者并集去重后返回 term 列表，交给 query_anchors 做确定性匹配。
        引擎本身零-ML；若调用方经 decomposer= 注入 LLM 回调，则本函数不被使用。
        """
        ql = (q + " " + (context or "")).lower()
        keys, seen = [], set()
        c = self._conn()
        rows = c.execute(
            "SELECT person,topic,event_date,location,tags FROM events").fetchall()
        for person_j, topic_j, edate, loc_j, tags_j in rows:
            # person / topic / location 现为 V2 字典 {规范名:[变体]}（旧 schema 列表兼容）
            for col in (person_j, topic_j, loc_j):
                d = json.loads(col or "{}") if col else {}
                if isinstance(d, dict):
                    items = [d]
                elif isinstance(d, list):
                    items = d
                else:
                    items = []
                for item in items:
                    if isinstance(item, dict):
                        name_map = item
                    elif isinstance(item, str) and item:
                        name_map = {item: []}
                    else:
                        continue
                    for canon, variants in name_map.items():
                        # 变体是用户声明的同义词别名：问句命中规范名或其任一变体，
                        # 即把「规范名 + 全部变体」都当检索词展开（双向接地：
                        # 用规范名提问也能匹配写了别名的锚点正文，反之亦然）。
                        names = [canon] + list(variants or [])
                        if any(n and n.lower() in ql for n in names):
                            # 反向门限：跨包常见词（≥_GROUND_PKG_GATE 包出现）非判别信号，
                            # 不再注入成检索词——压住「产出作品」把 OC 实体/泛词当变体
                            # 整批展开、把无关包顶上 TOP 的共现陷阱（T05/T07）。
                            if self._pkg_freq(canon) < _GROUND_PKG_GATE and canon not in seen:
                                seen.add(canon); keys.append(canon)
                            for n in names:
                                if n and self._pkg_freq(n) < _GROUND_PKG_GATE and n not in seen:
                                    seen.add(n); keys.append(n)
            if edate and edate.lower() in ql and edate not in seen:
                seen.add(edate); keys.append(edate)
            # —— 包级 tags 接地（请求 K 原型）：写入时 bake 的「规范解析名词」
            # —— 让读取时零-ML grounding 在问句/context 命中它时，能确定性把它
            # 当检索词展开（与四要素同机制，子串口径）。这是理解力前置写入时的
            # 推广：write-time AI 把判别性规范名词播种进 tags，read-time 不必靠
            # LLM 也能用同一套词表接地，省下 REFINE 分解器的调用（对零-ML 路径尤其划算）。
            # 纪律：tags 只放稀有/可区分的规范名词；通用词(用户/git/求职)塞入会触发共现陷阱，
            # 反把不相关文档顶上来——写入侧须克制。
            for tg in (json.loads(tags_j or "[]") if tags_j else []):
                # 反向门限：跨包常见 tag 非判别信号，不注入（纪律见上行注释）。
                if (isinstance(tg, str) and tg and tg.lower() in ql
                        and self._pkg_freq(tg) < _GROUND_PKG_GATE and tg not in seen):
                    seen.add(tg); keys.append(tg)
        # 内容词兜底（CJK 二元 + 英文去噪）
        for t in _reform_terms(q):
            if t not in seen:
                seen.add(t); keys.append(t)
        if keys:
            return keys
        toks = re.split(r"\s+", str(q).lower())
        return [t.strip(_PUNCT) for t in toks if t.strip(_PUNCT)]

    def _coverage(self, scored, terms):
        """top_k 锚点集合对查询词的 IDF 加权覆盖度（与 _anchor_score 同字段）。

        返回 0..1：命中词 IDF 权重和 / 查询词总 IDF 权重。复用 engine 内
        ts_covidf「内容词 distinct 覆盖 × 池内 idf」思路，是架构内原生概念。
        关键：判据必须与 _anchor_score 打分看的字段**一致**——title+about+tags+body，
        否则会出现「body 命中、about 未命中」的正确锚点被误拒（Veronica 实测 5/9
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
                for v in _flat_variants(fld):
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
        「词根+后缀」组合里，严格前后非 CJK 会误拒（黄蓝色的宝石→圣保罗之焰
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
            before_ok = (i == 0) or (not MechanicalMixin._is_cjk(text_l[i - 1]))
            j = i + L
            if j >= n:
                after_ok = True
            else:
                aj = text_l[j]
                # 后是方位/领域后缀 → 视为独立词（词根+后缀组合）；否则须非 CJK
                after_ok = (aj in MechanicalMixin._SUFFIX_FREE) or (not MechanicalMixin._is_cjk(aj))
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

        性能：优先用 search_blob 列 SQL 计频（O(命中) 而非全库逐文件读盘，
        实测全库扫 3000 文件≈2.8s → SQL 计频≈ms 级）。search_blob 含正文+锚点文本，
        比原 body-only 计频更贴近「语料真实频率」——锚点 about/keywords 频繁出现的
        词本就是高频、不应当稀有判别词（原 body-only 会漏计、误判稀有）。列未填充
        （旧库未 rebuild，search_blob 全 NULL）时 LIKE 漏 NULL 行会漏计→误判，
        故退回 body-only 逐文件读盘兜底（旧库零回归）。
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
            out = []
            for t in cl:
                n = c.execute("SELECT count(*) FROM events WHERE search_blob LIKE ?",
                              ("%" + str(t).lower() + "%",)).fetchone()[0]
                r = n / total
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
        # 逐文件读盘）。search_blob 已含正文+锚点文本，子串口径是最终 _boundary_hit
        # 判定的超集→边界判定只在候选上跑，精度不降、速度大幅升（实测全库扫 9000
        # 文件≈22s → SQL LIKE≈8ms）。
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
        NULL 行→假拒答，故降级 body 扫描）。子串预筛为超集，下游 _boundary_hit
        负责精确判定。
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
        return [r[0] for r in c.execute(sql, params).fetchall()]

    def _entity_in_corpus(self, term, pid=None):
        """判别实体是否真在语料（正文 OR 锚点文本任一出现即算有）。

        供拒答层『稀有实体全缺失 → 硬拒答』做存在性判定。此处用【子串】而非
        _boundary_hit：拒答路径的误伤是「过拒」(false-present→不拒→把真答案
        当域外丢掉)，故偏宽松；而 rare 过滤已剔除高频 2 字碎片(计算/公司/世界…)，
        残留稀有实体子串命中基本就是同一实体，碰撞误删风险可忽略。比仅扫正文更稳：
        实体仅落在锚点(title/about/keywords)也识别得到，不会被误拒。
        （对照 _corpus_top_term_hit_files 用 _boundary_hit 是另一条路：它的误伤是
        「漏拒」，故偏严——两条路径误差方向本就相反，匹配口径应相反。）

        性能：优先用 search_blob 列 SQL 子串判定（O(候选) 而非全库逐文件读盘，
        实测 9000 文件全扫≈22s → SQL LIKE≈8ms）；search_blob 已含正文+锚点文本，
        子串口径与原「正文 OR 锚点文本」一致。列未填充（旧库未 rebuild，search_blob
        全 NULL）时 LIKE 漏 NULL 行会假拒答，故退回逐文件读盘兜底（兼容旧库）。
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
            return False
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

    def _rep_anchor(self, fp):
        """为某 filepath 取一个代表锚点元组（与 scored 同构：rid,title,about,locator,score）。

        优先用 front-matter 首个锚点；无锚点（纯正文文件）则用文件名 stem 作代表。
        供 body 感知重排把答案锚定到正文真含判别词的文件时使用。score 给 0.0
        （代表锚点不参与 BM25 排序，仅作「该文件确有此事实」的落点证据）。
        """
        c = self._conn()
        row = c.execute("SELECT anchors FROM events WHERE filepath=?", (fp,)).fetchone()
        anchors = []
        if row and row[0]:
            try:
                anchors = json.loads(row[0]) or []
            except Exception:
                anchors = []
        d = next((a for a in anchors if isinstance(a, dict)), None)
        if d:
            return (fp,
                    d.get("title", "") or d.get("Chapter", ""),
                    d.get("about", "") or d.get("summary", ""),
                    d.get("locator", d.get("title", "") or d.get("Chapter", "")),
                    0.0)
        stem = os.path.splitext(os.path.basename(fp))[0]
        return (fp, stem, "", stem, 0.0)

    def _rare_anchor_hit(self, fp, rare):
        """该 doc 的 front-matter 锚点是否直接命中任一 rare 判别词（title/about/keywords）。

        用于 body-aware rerank 的「密度并列」兜底：锚点自身就讲该判别词 → 文档『关于』
        查询的概率更高，应排在仅正文顺带提及的 doc 之前。例：「项目名」题 什么是AIMH系统
        锚点讲项目命名 → 胜出；SCHEMA 仅正文含词、锚点不命中 → 落败。此兜底**不伤**
        body-only 救援（误删脚本事件）：救援 doc（用户数据）锚点本就不命中判别词、
        靠 density 主序保位，distractor（存储架构总览）锚点也只命中泛词「架构」、不命中
        判别词 → 两者 rare_anchor_hit 同为 0、退回原 filepath 并列，位置不变。
        """
        if not rare:
            return 0
        c = self._conn()
        row = c.execute("SELECT anchors FROM events WHERE filepath=?", (fp,)).fetchone()
        if not row or not row[0]:
            return 0
        try:
            anchors = json.loads(row[0]) or []
        except Exception:
            return 0
        rl = {t.lower() for t in rare}
        for a in anchors:
            if not isinstance(a, dict):
                continue
            # 只查锚点的「描述性文本」(title/Chapter/about/summary)，不查 keywords/tags
            # —— 后者是结构化标签，distractor 常借 cross-reference 关键词顺带带上判别词
            # （如「误删脚本事件」题 存储架构总览 的 keywords 提误删），会误抬 distractor。
            blob = " ".join(str(a.get(k, "")) for k in
                           ("title", "Chapter", "about", "summary")).lower()
            if any(t in blob for t in rl):
                return 1
        return 0

    def _body_aware_rerank(self, scored, terms, top_k, pid=None, hit_files=None):
        """语料包含性命中后，把答案重排到正文真含稀有实体的文件（治本之「精准」）。

        scored 是 BM25 锚点弱命中（可能因 rebuild 未派生 body 锚点而命中错包）。
        重排策略——按"文件命中稀有实体密度"排序，而非简单"含词即置顶"：
          概念词常跨包共现（用户数据也详述 AIMH），光"含词"无法区分 design-journal
          真答案与用户数据顺带提及；只有按"正文含多少稀有特异实体"降序，才能让真
          答案包（密度更高）排前。
          1) scored 里正属命中文件的锚点优先，且在该组内按稀有实体密度降序；
          2) 若 scored 全部不属命中文件（BM25 未召回正文文件），则主动从 corpus
             命中文件构造代表锚点（见 _rep_anchor）按密度排序塞到最前。
        返回与 scored 同构的 filepath 元组列表（供 _stemify 后返回）。
        """
        if not terms:
            return scored[:top_k]
        rare = self._rare_entities(terms, pid)
        # 文件「稀有实体命中密度」= 正文含多少 rare 词（越多越可能是真答案包）。
        # ⚠️ 正文必须走 read_body(fp)（全路径），与 _corpus_top_term_hit_files 同源：
        # _pkg_body(rid) 在全局句柄下把 stem 传给 read()，常解析失败返回空体 →
        # density 恒 0 → 误删脚本等 body-only 事实永远沉底（G2-Q5 回归根因）。
        def _density(fp):
            b = self.read_body(fp) or ""
            if not rare:
                return 0
            # ⚠️ 计【出现次数】而非【不同词数】：「详述该事件的文件」(用户数据 多次
            # 提及 误删/脚本) 应胜过「仅顺带 cross-reference 一次的文件」(SCHEMA/
            # 用户操作手册 提一次)。否则密度按不同词计数时两者并列、靠 filepath 兜底，
            # 真答案(body-only 救援) 被高密度 distractor 挤出 top-5（误删脚本题回归根因）。
            bl = b.lower()
            return sum(bl.count(t.lower()) for t in rare)
        if not hit_files:
            hit_files = self._corpus_top_term_hit_files(terms, pid)
        if not hit_files:
            return scored[:top_k]
        hit_set = set(hit_files)
        scored_ids = {s[0] for s in scored}
        # 1) body_hit：锚点池(scored)里命中文件的真锚点（保留原始 about/locator），
        #    按正文稀有实体密度降序——真答案包（含判别词最多）自然居前。
        body_hit = [s for s in scored if s[0] in hit_set]
        # 2) added：命中但不在锚点池、且正文真含稀有实体(density>0)的 body-only 事实
        #    （如「误删脚本事件」「文档写给谁看」仅落正文）→ 有界补加（最多 2 个，
        #    取密度最高者）按密度降序。density=0 的「含词」噪音代表锚点绝不纳入
        #    （Edit 7 回归根因：无差别前置把 BM25 真答案挤出 top-5）。
        added = []
        for fp in hit_files:
            if fp in scored_ids:
                continue
            if _density(fp) <= 0:
                continue
            # ⚠️ 排除「日记类」文件（stem 以 daylog 开头）：日记是包罗万象的流水账，
            # 正文常顺带提及一切术语，按密度会被误推到真答案锚点之前（如「resolver
            # 循环」被 daylog-2026-08-13 以 score=0.0 抢 top1 的重排越权）。日记内容
            # 已由 linked-BFS / 上下文覆盖，不应作为精准答案锚点被密度重排抬举。
            stem = os.path.splitext(os.path.basename(fp))[0]
            if stem.lower().startswith("daylog"):
                continue
            added.append(self._rep_anchor(fp))
        added.sort(key=lambda s: (-_density(s[0]),
                                   -self._rare_anchor_hit(s[0], rare), s[0], s[1]))
        added = added[:2]
        # 3) 命中代表 = body_hit ∪ added，整体按密度降序；**密度并列时以
        #    「锚点是否命中 rare 判别词」(rare_anchor_hit) 兜底**——锚点自身就讲该
        #    判别词的 doc 比仅正文顺带提及的 doc 更『关于』查询，应居前（修「项目名」
        #    题 SCHEMA 以 sc=0 靠 filepath 并列抢 top1 的越权）；又不伤 body-only 救援
        #    （救援 doc 与 distractor 锚点都不命中判别词 → 同归 0、退回原 filepath 并列）。
        #    密度仍为主序，BM25 分此处不参与排序（避免泛词高 BM25 的 distractor 反超
        #    body-only 真答案，如「误删脚本事件」题）。
        pool = body_hit + added
        pool.sort(key=lambda s: (-_density(s[0]),
                                 -self._rare_anchor_hit(s[0], rare), s[0], s[1]))
        added_ids = {a[0] for a in added}
        rest = [s for s in scored if s[0] not in hit_set and s[0] not in added_ids]
        # 4) 拼接并截断 top_k：命中代表 → rest
        ordered = pool + rest
        truncated = ordered[:top_k]
        # 5) OR-fail-safe：原 BM25 最佳 top_k 的 gold 锚点永不被挤出（保召回下限）。
        #    ⚠️ 但「语料包含性救援」进来的 pool 成员（body-only 真答案，如「误删脚本
        #    事件」的 用户数据）本就不在 scored[:top_k]（其锚点 BM25=0），若按旧逻辑
        #    keep[:top_k-len(missing)] 从尾部截断，会把救援项挤掉、改塞回 scored[:top_k]
        #    里的【非语料命中】distractor（如 什么是AIMH系统）——方向完全反了。修正：
        #    pool 成员（语料真含判别词的文件）永不因 fail-safe 被丢弃，溢出只从 rest
        #    （非语料命中、仅 BM25 高分的尾巴）裁，且 pool 自身也只取 top_k 内的高位。
        orig_top = scored[:top_k]
        trunc_ids = {t[0] for t in truncated}
        missing = [s for s in orig_top if s[0] not in trunc_ids]
        if missing:
            pool_ids = {p[0] for p in pool}
            extra = [s for s in missing if s[0] not in trunc_ids]
            truncated = truncated + extra
            if len(truncated) > top_k:
                # 先保 pool（语料命中救援）高位，溢出只裁 rest；pool 自身也截断到 top_k
                pool_part = [t for t in truncated if t[0] in pool_ids][:top_k]
                rest_part = [t for t in truncated if t[0] not in pool_ids]
                rest_keep = rest_part[:max(0, top_k - len(pool_part))]
                truncated = pool_part + rest_keep
        return truncated

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
        # ② 长中文整句串（len>4：_reform_terms 保留的整问句，锚点永远精确命中不了，
        #    只把 w_total/thr 顶高，如「是哪几个铁律」idf=3.5）。
        # 二者都让跨包常见真词（架构/记忆/铁律，IDF 低）被误滤（design-journal 误拒根因）。
        # 仅作用于阈值计算；BM25 召回仍走完整 terms（不动召回）。
        disc = [t for t in terms
                if len(str(t)) <= 4 and not _is_garbage_bigram(str(t))]
        if not disc:
            return scored
        w_total = sum(self._idf(t) for t in disc)
        if w_total <= 0:
            return scored
        thr = theta * w_total
        # 自归一锚点：查询中判别力最强的单 term IDF，用作「命中判别词即保」的底线。
        # 治 over-abstain 根因：_understand_query 的四要素 grounding 会把稀有变体
        # (如 黄蓝色的宝石/蓝钻/深海蓝橙焰钻石/那颗钻石) 注入 terms，其 IDF 撑高
        # w_total→thr 极高；而锚点只命中 宝石/圣保罗之焰 这类真判别词(rel 远<thr)
        # 被误删→empty_pool 过度拒答。补「锚点确含任一高判别实体词即保」通道：
        # 锚点若匹配到 ≥floor(=查询最强判别词 IDF 的一半) 的词，判定为相关、保活。
        # 纯噪声锚点只命中 作者/天气 等通用词(IDF 远低于 floor)→仍被滤→交由 _abstain 拒答。
        # floor 用【判别词表】max（已剔垃圾二元+长整句串）——虚高 IDF 词(么类/忆架/
        # 是哪几个铁律) 会顶爆 floor，使跨包常见真词(架构/记忆/铁律) 保不住（design-journal
        # 误拒根因）。匹配段仍用全 terms（垃圾词命中给 rel 加分但权重小，无碍）。
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

        Gate1（low_coverage）语义升级为「语料包含性」：
          top_k 锚点覆盖 < kappa 不再直接拒答，而是先看查询**最判别词**是否真在
          语料里——在 → 领域内事实（只是没被锚定/锚点弱）→ 低置信返回当前最佳
          锚点，绝不误拒；不在 → 语料真缺该实体 → 拒答。这把「拒答=锚点弱」修正为
          「拒答=语料无该实体」，治本解决正文 ### 段事实被过度拒答的问题。
        """
        if not scored:                       # Gate 0 · 空池
            return {"answer": [], "abstain": True,
                    "reason": "empty_pool", "confidence": "none",
                    "message": ABSTAIN_DEFAULT_MSG}
        cov = self._coverage(scored, terms)
        # 语料包含性兜底（治本）：只要查询**稀有且边界独立**的实体真在语料正文，
        # 就把含该事实的正文文件提到最前（body-only 事实不再被锚点弱匹配永久压底）；
        # 2 字碎片需足够特异（≤8% 文件）才计入，过滤 计算/公司/世界/小说 等通用
        # 2 字子串碰撞 → 域外问题正常拒答、域内问题（误删/拒答层/写给）不误拒。
        # 命中检测走【全库】（pid=None），不被查询→包路由缩圈——跨包概念共现时
        # 真答案常落在非路由包（如「误删脚本」在 用户/用户数据.md、「文档写给谁看」
        # 在 用户/用户数据.md），路由缩圈会把它们排除在命中范围外。
        hit_files = self._corpus_top_term_hit_files(terms, None)
        if hit_files:
            ans = self._body_aware_rerank(scored, terms, top_k, pid, hit_files)
            return {"answer": ans, "abstain": False,
                    "reason": "corpus_hit_rerank",
                    "confidence": "low" if cov < kappa else "high"}
        # 反相拒答闸（治本，仅 AI 接口模式启用）：查询含稀有判别实体，但语料
        # 正文/锚点【任一都查不到】→ 域内确无该实体 → 直接拒答。补上
        # corpus_hit_rerank「有命中才放行」缺失的半边。
        # 仅当 terms 来自 AI 接口(keywords/decomposer) 时启用：机械拆词
        # (_understand_query) 抽不出『量子计算/回旋镖』这类复合实体，稀有过滤
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

