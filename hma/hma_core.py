"""
HMA - Hybrid Memory Architecture (AM 正文 + 薄 CEMA 索引)
==========================================================

零依赖核心库。设计原则（来自 hybrid-memory-architecture.md）：

  1. 前后台严格 1:1：每个事件包 = 一个 .md 正文 + 索引中恰好一条记录
  2. .md 是权威源：SQLite 索引可由所有 .md 的 front-matter 重建
  3. 无状态检索：确定性索引查找（关键词/别名/Tag），不依赖热度/权重/新鲜度
  4. 廉价存储、不遗忘：正文默认冷存储，按需按 ID 取
  5. 主题而非时间线：写入即按事件分类
  6. Agent 直写：LLM 直接写/改 .md，索引 upsert 是确定性微操作

仅使用 Python 标准库（sqlite3 / json / re / os / hashlib）。
"""

import os
import re
import json
import shutil
import sqlite3
import math
from collections import Counter
from datetime import date, timedelta

# 公共路由层（查询→包/作用域）：从 hma_core 抽出为单一真相源。
# routing 模块惰性导入本模块的符号，故此处顶层导入无循环依赖风险。
from . import routing
from .mechanical import (
    MechanicalMixin,
    _PUNCT, _STOPWORDS, normalize_terms, _REFORM_STOP, _reform_terms,
    _flat_variants, _GROUND_PKG_GATE, _KW_FIXED, _KW_BIGRAM_BONUS,
    _GARBAGE_FUNC, _is_garbage_bigram, ABSTAIN_KAPPA, ABSTAIN_HIGH_K,
    ABSTAIN_DEFAULT_MSG,
)


# 变更快照系统已废弃（R59 续3）：write 不再落 changes/，
# 修改标记改由 front-matter 的 `updated:` 字段承担（每次 write 刷新）。


# ---------------------------------------------------------------------------
# 查询分词（query / query_anchors 共用，保证两层口径一致）
# ---------------------------------------------------------------------------






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


# 歧义门阈值：去重后实体候选数达到此值即判歧义 → 交交互澄清（默认 2）。
MIN_CANDIDATES = 2

# 字段中心度层级：person 规范名/别名 最靠近身份核心，tags 最边缘。
# 独有弧段排序时，同判别度优先展示更靠近圆心的性质（特异性梯度）。
_FIELD_TIER = {"person": 4, "kw": 3, "topic": 2, "tags": 1, "location": 2}

# front-matter 字段分类（供 _parse_fm 块解析分发）
_FM_SPECIAL = {"anchors", "features", "person", "location", "topic"}  # JSON 优先解析
_FM_LIST = {"tags", "linked", "anchors"}                              # 空 block → []
_FM_DICT = {"person", "location", "topic"}                            # 空 block → {}


# ---------------------------------------------------------------------------
# V2 四要素字段辅助（person / location / topic 一律为 {canonical:[variants]} 字典）
# ---------------------------------------------------------------------------
def _as_four(val):
    """四要素字段归一：None→{}；list[名称]→{名称:[]}；list[dict]→合并为 dict；
    dict 原样（值规整为列表）。

    兼容 V2 规范文件格式 [{规范名:[变体]}, …]（首级 list、每项单键 dict）——
    此前只认 list[str] 与 dict，遇 list[dict] 会触发 unhashable 崩溃。
    """
    if val is None:
        return {}
    if isinstance(val, dict):
        return {k: (list(v) if v else []) for k, v in val.items()}
    if isinstance(val, list):
        out = {}
        for item in val:
            if isinstance(item, dict):
                for k, vs in item.items():
                    out.setdefault(k, [])
                    for v in (vs or []):
                        if v not in out[k]:
                            out[k].append(v)
            elif item:
                out[item] = []
        return out
    return {}


def _merge_legacy(person, aliases, features):
    """把遗留 aliases(列表)/features({canon:[变体]}) 折叠进 person dict（V2 无独立列）。

    迁移保底：旧格式 .md（含 aliases/features 行、person 为列表）经此并入四要素
    字典，rebuild 后旧数据不丢、落到 V2 字段族。
    """
    d = _as_four(person)
    for a in (aliases or []):
        if a in d:                      # 已是某规范名，跳过（不把规范名当变体）
            continue
        if d:
            first = next(iter(d))
            if a not in d[first]:
                d[first].append(a)
        else:
            d[a] = []
    for canon, vs in (features or {}).items():
        d.setdefault(canon, [])
        for v in (vs or []):
            if v not in d[canon]:
                d[canon].append(v)
    return d


def _four_to_list(val):
    """合并 dict 形式的四要素 → 规范 front-matter 列表形式 [{规范名:[变体]}, …]。

    每项规定名拆成独立单键 dict（符合用户拍板的 [{规范名:[变体]}] 首级 [ ] 形态），
    供 to_markdown 序列化；若入参已是 list（含 list[dict] / list[str]）则规整后原样返回。
    """
    if isinstance(val, dict):
        return [{k: (list(v) if v else [])} for k, v in val.items()]
    if isinstance(val, list):
        out = []
        for item in val:
            if isinstance(item, dict):
                out.append({k: (list(v) if v else []) for k, v in item.items()})
            elif item:
                out.append({item: []})
        return out
    return val






# 四要素软加权（理解层字段族）用的地点/月份词典。确定性、零 ML。
_LOC_WORDS = frozenset({
    'home', 'school', 'restaurant', 'park', 'office', 'gym', 'hospital', 'airport',
    'library', 'cafe', 'bar', 'store', 'mall', 'beach', 'lake', 'city', 'town',
    'kitchen', 'garden', 'building', 'university', 'college', 'work', 'apartment',
})
# 四要素权重（topic 用连续命中数，其余 0/1）：person / time / topic / location
_FIELD_W = (4, 3, 2, 2)   # person, time, topic(+tags), location

# 字段加权折进 score 的封顶参数：mc/bonus 不再作主排序键，而是作为【有上限的加法项】
# 折进文本分，确保"文本相关度"为主排序、字段仅作轻推（修 T11/T08/T03 整包被 topic/tags
# 子串顶到真答案前）。_FIELD_CAP=字段贡献不超过文本分×此比例。
_FIELD_NUDGE = 2.0   # 每命中 1 个结构化要素的基础 nudges（再经 _FIELD_CAP 封顶）
_FIELD_CAP = 0.3

def _field_term_hit(term, field_tokens):
    """topic/tags 命中判定：ascii 词要求【整词/规范名精确匹配】，防
    corpus_missing⊂corpus_missing_entity 这类子串误判把无关包整包顶起；
    CJK 词允许子串（架构⊂存储架构 属期望命中）。field_tokens 为小写后的
    topic 规范名/变体 + 包级 tags 集合。"""
    if any(c.isascii() and c.isalnum() for c in term):
        return term in field_tokens
    return any(term in t for t in field_tokens)

# ---------------------------------------------------------------------------
# 时间解析（确定性、零 ML）
# ---------------------------------------------------------------------------
# 问句里的时间线索有三种形态，此前只认「四位年份 + 三字母月份缩写」，
# 导致 "January 29, 2024" / "early April 2024" / "90 days ago" 全部解析不到。
# 这里做一个统一入口 parse_time_hint()，供检索层与各基准适配器共用。

# 月份词典：三字母缩写与全称都认（"jan" / "january" 同归 1）
_MONTH_ALIASES = {}
for _i, (_ab, _full) in enumerate([
    ('jan', 'january'), ('feb', 'february'), ('mar', 'march'), ('apr', 'april'),
    ('may', 'may'), ('jun', 'june'), ('jul', 'july'), ('aug', 'august'),
    ('sep', 'september'), ('oct', 'october'), ('nov', 'november'), ('dec', 'december'),
], 1):
    _MONTH_ALIASES[_ab] = _i
    _MONTH_ALIASES[_full] = _i
    _MONTH_ALIASES[_full[:4]] = _i          # "sept"
_MONTH_RE = "|".join(sorted(set(_MONTH_ALIASES), key=len, reverse=True))

# 英文数词 → 数值（相对时间 "two months ago" 用）
_NUM_WORDS = {
    'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11,
    'twelve': 12, 'couple': 2, 'few': 3, 'several': 3,
}
_UNIT_DAYS = {'day': 1, 'week': 7, 'month': 30, 'year': 365}

# 注意尾部用 (?!\d) 而非 \b：事件日期常带时间戳（2024-01-20T19:12:00），
# 用 \b 会因 "20T" 无词边界而回溯掉「日」，把日级信号退化成月级。
_RE_ISO = re.compile(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?(?!\d)")
_RE_MDY = re.compile(r"\b(%s)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,)?\s*(\d{4})?\b"
                     % _MONTH_RE)
_RE_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(%s)[a-z]*\.?\s*(\d{4})?\b" % _MONTH_RE)
_RE_MY = re.compile(r"\b(%s)[a-z]*\.?\s*,?\s+(\d{4})\b" % _MONTH_RE)
_RE_PART = re.compile(r"\b(early|mid|middle|late|beginning of|end of)[\s\-]+(%s)[a-z]*\b"
                      % _MONTH_RE)
_RE_REL = re.compile(
    r"\b(?:about|approximately|around|almost|nearly|roughly|over)?\s*"
    r"(\d+|%s)\s+(?:simulated\s+)?(day|week|month|year)s?\s+ago\b"
    % "|".join(_NUM_WORDS))
_RE_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_PART_RANGE = {'early': (1, 10), 'beginning of': (1, 10), 'mid': (11, 20),
               'middle': (11, 20), 'late': (21, 31), 'end of': (21, 31)}


class TimeHint:
    """一次查询里解析出的时间意图。不剔除任何候选，只用于软加权调序。

    粒度分级（match 返回值）：
        3 = 精确到日命中（显式日期，或落在窄窗口内）
        2 = 精确到月命中（年月对，或月份词命中）
        1 = 只有年份信号且年份命中（粗，仅当没有更细信号时才给分）
        0 = 无命中
    年份单独命中默认不计分：单年语料里「2024」全体候选都命中，零区分度，
    计分只会把噪声抬到与真实信号同级。
    """

    __slots__ = ("years", "months", "ym", "days", "windows")

    def __init__(self, years=None, months=None, ym=None, days=None, windows=None):
        self.years = set(years or ())
        self.months = set(months or ())
        self.ym = set(ym or ())
        self.days = set(days or ())
        self.windows = list(windows or ())

    def __bool__(self):
        return bool(self.years or self.months or self.ym or self.days or self.windows)

    @property
    def fine(self):
        """是否含比「年」更细的信号。"""
        return bool(self.months or self.ym or self.days or self.windows)

    def match(self, edate):
        """候选事件日期 edate（ISO 字符串）与本意图的匹配等级 0-3。"""
        if not edate or not self:
            return 0
        m = _RE_ISO.search(edate)
        if not m:
            return 0
        y, mo = int(m.group(1)), int(m.group(2))
        d = int(m.group(3)) if m.group(3) else None
        day = None
        if d:
            try:
                day = date(y, mo, d)
            except ValueError:
                day = None

        if day and day in self.days:
            return 3
        for lo, hi in self.windows:
            if day and lo <= day <= hi:
                # 窄窗口（≤11 天，含 early/mid/late 的旬窗）视为日级命中；
                # 相对时间的宽容差窗口只算月级，避免把模糊线索抬到与精确日同级。
                return 3 if (hi - lo).days <= 11 else 2
        if (y, mo) in self.ym:
            return 2
        if mo in self.months:
            return 2
        if y in self.years and not self.fine:
            return 1
        return 0


def parse_time_hint(text, now=None):
    """从自然语言问句抽取时间意图。纯正则 + 词典，确定性、零 ML。

    支持：
      * ISO             2024-01-29 / 2024-01
      * 月日年          January 29, 2024 / Jan 29 / 29 January 2024
      * 月年            April 2024
      * 段落修饰        early/mid/late April（→ 该月 1-10 / 11-20 / 21-末）
      * 相对时间        90 days ago / two months ago / almost a year ago
                        （含 MemoryStress 的 "55 simulated days ago"）
    `now` 为相对时间的锚点（date 或 ISO 字符串）；缺省时相对时间不解析，
    因为没有锚点的「90 天前」无法落到具体日期。
    """
    t = str(text or "").lower()
    if not t:
        return TimeHint()
    if isinstance(now, str):
        m = _RE_ISO.search(now)
        now = date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)) if m else None

    years, months, ym, days, windows = set(), set(), set(), set(), []

    for m in _RE_ISO.finditer(t):
        y, mo = int(m.group(1)), int(m.group(2))
        if m.group(3):
            try:
                days.add(date(y, mo, int(m.group(3))))
            except ValueError:
                ym.add((y, mo))
        else:
            ym.add((y, mo))
        years.add(y)

    for rx, order in ((_RE_MDY, "mdy"), (_RE_DMY, "dmy")):
        for m in rx.finditer(t):
            if order == "mdy":
                mon, dd, yy = m.group(1), m.group(2), m.group(3)
            else:
                dd, mon, yy = m.group(1), m.group(2), m.group(3)
            mo = _MONTH_ALIASES.get(mon)
            if not mo:
                continue
            months.add(mo)
            y = int(yy) if yy else (now.year if now else None)
            if y:
                years.add(y)
                try:
                    days.add(date(y, mo, int(dd)))
                except ValueError:
                    ym.add((y, mo))

    for m in _RE_MY.finditer(t):
        mo = _MONTH_ALIASES.get(m.group(1))
        if mo:
            months.add(mo)
            years.add(int(m.group(2)))
            ym.add((int(m.group(2)), mo))

    for m in _RE_PART.finditer(t):
        part, mon = m.group(1), m.group(2)
        mo = _MONTH_ALIASES.get(mon)
        if not mo:
            continue
        months.add(mo)
        lo_d, hi_d = _PART_RANGE.get(part, (1, 31))
        # 年份取同句里出现的年份，否则取锚点年
        yy = None
        ym_hit = [y for (y, mm) in ym if mm == mo]
        if ym_hit:
            yy = ym_hit[0]
        elif years:
            yy = max(years)
        elif now:
            yy = now.year
        if yy:
            try:
                lo = date(yy, mo, lo_d)
                hi_day = min(hi_d, [31, 29 if yy % 4 == 0 else 28, 31, 30, 31, 30,
                                    31, 31, 30, 31, 30, 31][mo - 1])
                windows.append((lo, date(yy, mo, hi_day)))
            except ValueError:
                pass

    if now:
        for m in _RE_REL.finditer(t):
            raw, unit = m.group(1), m.group(2)
            n = int(raw) if raw.isdigit() else _NUM_WORDS.get(raw)
            if not n:
                continue
            delta = n * _UNIT_DAYS[unit]
            # 容差随跨度放大：近处要准，远处本就模糊（"大约 210 天前"）
            tol = max(2, int(round(delta * 0.1)))
            target = now - timedelta(days=delta)
            windows.append((target - timedelta(days=tol), target + timedelta(days=tol)))

    for m in _RE_YEAR.finditer(t):
        years.add(int(m.group(0)))

    # 中文数字月份（缺口 B）：生产原 parse_time_hint 只认英文月名/ISO，不认「3月/三月」。
    # 补「2026年3月」「3月10日」「三月」「三月十日」四类中文时间表达；与既有英文/ISO
    # 解析互不冲突（lookbehind 避免与「年3月」重复计入）。纯正则+词典，确定性、零 ML。
    _CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
               "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}
    for m in re.finditer(r"(\d{4})\s*年\s*([一二三四五六七八九十]|\d{1,2})\s*月", t):
        y = int(m.group(1))
        mo = int(m.group(2)) if m.group(2).isdigit() else _CN_NUM[m.group(2)]
        years.add(y)
        months.add(mo)
        ym.add((y, mo))
    for m in re.finditer(r"(?<![\d年])\s*([一二三四五六七八九十]|\d{1,2})\s*月\s*(\d{1,2})?\s*日?", t):
        mo = int(m.group(1)) if m.group(1).isdigit() else _CN_NUM[m.group(1)]
        months.add(mo)
        if m.group(2):
            d = int(m.group(2))
            yy = max(years) if years else (now.year if now else None)
            if yy:
                try:
                    days.add(date(yy, mo, d))
                except ValueError:
                    ym.add((yy, mo))

    return TimeHint(years, months, ym, days, windows)


# 并集/聚合意图识别（缺口 ②）：仅保留真·聚合词；「这些/那些/各」只是指示代词不算。
_UNION_AGG = ("都", "全", "各自", "分别", "共同", "所有")
_UNION_CONN = ("以及", "还有", "另外", "一并", "一起")


def _is_union_query(q):
    """识别「并集/聚合」查询意图，避免被歧义门误判为待消歧。"""
    q = str(q or "")
    return any(a in q for a in _UNION_AGG) or any(c in q for c in _UNION_CONN)












def _time_tiebreak(edate, updated):
    """确定性时间 tie-break 键（机制A：事件时间近因，平局裁决、不破 §13）。

    排序语义：有事件日期优先且其值（ISO 字符串）新者在前；无事件日期
    （空 / 哨兵 "—"）时退化为包写入/更新时间（updated，同样新者在前）。
    仅作用于『相关性分数相等』的候选之间，不构成全量时间重排，故不抢
    占高相关旧内容的位次（如 daylog 顺带提及的无关条目不会被新鲜度顶前）。
    """
    from datetime import datetime as _dt

    def _ord(s):
        if not s:
            return 0
        try:
            return _dt.fromisoformat(s[:19] if "T" in s else s).timestamp()
        except Exception:
            return 0

    e = edate if (edate and edate != "—") else ""
    u = updated or ""
    # 有事件时间优先；同状态按时间戳降序（新者前）→ 用负值使升序即「新在前」。
    return (0 if e else 1, -_ord(e), -_ord(u))


def _anchor_score(at, asum, atags, abody, ql, terms, w):
    """单个「文本块」（一段锚点，或一个事件包的全部锚点拼成的虚拟块）的计分。

    ql 为原始查询串；terms 为归一化后的 term 列表；w 为 term→权重映射
    （idf 模式为 IDF 权重，否则全 1）。逐字段累加，精确串匹配（ql==at、
    ql in abody、tag 精确）给固定加分，逐词子串命中按权重加分。
    """
    s = 0
    if ql == at:
        s += 80
    else:
        for t in terms:            # 逐词累加：多词全中 > 仅中一词
            if t in at:
                s += 50 * w[t]
    for t in terms:
        if t in asum:
            s += 30 * w[t]
    for t in atags:
        if ql == t:
            s += 40
        else:
            for term in terms:
                if term in t:
                    s += 30 * w[term]
                    break
    # 段内正文扫描（修订核心）：L2 现在能看见段内文字，不仅是首句摘要
    if ql in abody:
        s += 25
    for t in terms:
        if t in abody:
            s += 10 * w[t]
    # 关键词比对加分（用户提议“命中就加权”的精炼版）：查询里每个命中关键词加分，
    # 但按 idf 平方加权——稀有词（如本例 周会，仅周会包含）权重被放大，常见词权重低。
    # 这样“命中用户原话里的稀有判别词”能压倒对方“命中一大堆常见词”的体积和，
    # 解决 flat 加分反而帮了命中更多常见词的包、以及小索引 idf 被 +1 地板压扁的问题。
    covered = set()
    for t in terms:
        hit = (t in at) or (t in asum) or (t in abody)
        if not hit:
            for tg in atags:
                if t in tg:
                    hit = True
                    break
        if hit:
            covered.add(t)
    if covered:
        # 关键词「覆盖度」奖励：查询词只要被本锚点覆盖（命中≥1 个真实词），
        # 即给一次性 +200，不再按命中词数量 ×N——避免长/无关文档靠堆词虚高。
        # （逐词子串命中已在上方 at/asum/abody 计分里按词数区分，覆盖度只作布尔信号。）
        real_hits = [t for t in covered if not _is_garbage_bigram(t)]
        garbage_hits = [t for t in covered if _is_garbage_bigram(t)]
        if real_hits:
            s += _KW_FIXED
        s += _KW_BIGRAM_BONUS * len(garbage_hits)
    return s


def _search_blob(pkg):
    """构造小写可检索 blob（标题+四要素+tags+linked+各锚点 Chapter/about/keywords+body），
    供 query_anchors / _understand_query 以 SQL LIKE 做【语义等价】候选预筛，
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


# ---------------------------------------------------------------------------
# 事件包：front-matter（索引字段）+ 正文（语义内容）
# ---------------------------------------------------------------------------

class EventPackage:
    """一个事件包：YAML front-matter + Markdown 正文。"""

    def __init__(self, id="", title="", summary="", aliases=None, tags=None,
                 linked=None, created=None, updated=None, body="", anchors=None,
                 person=None, location=None, topic=None, event_date=None,
                 features=None, path=None):
        self.id = id                      # 文件名 stem（内存标识，非存储列）
        self.title = title
        self.summary = summary
        # 兼容旧调用：aliases / features 仅作临时入参，最终并入四要素 dict
        self._aliases_hint = list(aliases) if aliases else None
        self._features_hint = features or None
        self.tags = tags or []
        self.linked = linked or []
        self.created = created or str(date.today())   # 内存名；DB 列 = pkage_created
        self.updated = updated or str(date.today())   # 内存名；DB 列 = pkage_updated
        self.body = body
        self.anchors = anchors or []
        # 四要素（V2 一等字段）：一律 {canonical:[variants]} 字典；兼容旧 list
        self.person = _as_four(person)
        self.location = _as_four(location)
        self.topic = _as_four(topic)
        self.event_date = event_date or ""
        # 来源路径（读取时回填；非 front-matter 字段，不参与序列化）。
        self.path = path

    @property
    def aliases(self):
        """派生：四要素所有规范名 + 变体（V2 不再有独立 aliases 列）。"""
        out = list(self._aliases_hint) if self._aliases_hint else []
        for d in (self.person, self.topic, self.location):
            for k, vs in (d or {}).items():
                out.append(k)
                out.extend(vs or [])
        seen, res = set(), []
        for x in out:
            if x not in seen:
                seen.add(x)
                res.append(x)
        return res

    @property
    def features(self):
        """派生：{canonical:[变体]}（V2 不再有独立 features 列，由四要素推导）。"""
        out = dict(self._features_hint or {})
        for d in (self.person, self.topic, self.location):
            for k, vs in (d or {}).items():
                out.setdefault(k, [])
                for v in (vs or []):
                    if v not in out[k]:
                        out[k].append(v)
        return out

    # ---- 序列化（写 .md）------------------------------------------------
    @staticmethod
    def _fmt_list(values):
        out = []
        for v in values:
            v = str(v)
            if ("," in v) or ('"' in v) or ("'" in v):
                v = '"' + v.replace('"', "'") + '"'
            out.append(v)
        return "[ " + ", ".join(out) + " ]"

    def _fmt_anchors_block(self):
        """anchors 多行 block 输出（v3：每锚点 3 行，Chapter/about/keywords 各占一行；
        keywords 为单行内联 JSON 列表，不逐条分行）。

        对齐 _parse_fm 的 block 换行式路径：
          anchors:
            - Chapter: "<json>"
              about: "<json>"
              keywords: ["<json>", "<json>"]
        解析侧由 _parse_seq/_parse_mapping 无损还原，索引加载(from_markdown_fm_only)
        与全量读取(from_markdown) 共用 _parse_fm，故 rebuild 后 keywords 不丢。
        """
        if not self.anchors:
            return []
        out = ["anchors:"]
        for a in self.anchors:
            ch = json.dumps(a.get("Chapter", ""), ensure_ascii=False)
            about = json.dumps(a.get("about", ""), ensure_ascii=False)
            kws = a.get("keywords") or []
            out.append(f"  - Chapter: {ch}")
            out.append(f"    about: {about}")
            out.append(f"    keywords: {json.dumps(kws, ensure_ascii=False)}")
        return out

    def to_markdown(self):
        fm = [
            "---",
            f"title: {self.title}",
            f"summary: {self.summary}",
            f"tags: {self._fmt_list(self.tags)}",
            f"linked: {self._fmt_list(self.linked)}",
            # 四要素固定顺序输出（与用户拍板的字段顺序一致）；空字段也保留为 []，
            # 避免程序化写回时丢失字段、破坏「title→…→location→topic→…」固定顺序契约。
            f"person: {json.dumps(_four_to_list(self.person), ensure_ascii=False)}",
            f"event_date: {self.event_date or '—'}",
            f"location: {json.dumps(_four_to_list(self.location), ensure_ascii=False)}",
            f"topic: {json.dumps(_four_to_list(self.topic), ensure_ascii=False)}",
            *self._fmt_anchors_block(),
            f"pkage_created: {self.created}",
            f"pkage_updated: {self.updated}",
            "---",
            "",
            self.body if self.body.endswith("\n") else self.body + "\n",
        ]
        return "\n".join(fm)

    # ---- 反序列化（读 .md）----------------------------------------------
    @classmethod
    def from_markdown(cls, text, filepath=None):
        # front-matter 必须用「独立行 ---」作边界（首尾各一个），
        # 不能用 text.split("---") —— 正文 / 内联锚点 body 里常含字面
        # `---`（如本规格文档），按子串切会把 front-matter 拦腰截断，
        # 导致 anchors 被误读成字符串并二次 JSON 编码污染索引。
        if not text.lstrip().startswith("---"):
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body=text.strip())
        lines = text.splitlines()
        if lines[0].strip() != "---":
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body=text.strip())
        # 找下一条「独立 --- 行」作为 front-matter 结束符
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body=text.strip())
        fm_text = "\n".join(lines[1:end])
        body = "\n".join(lines[end + 1:]).lstrip("\n")
        fm = cls._parse_fm(fm_text)
        # 若 front-matter 里的 anchors JSON 因含换行被解析器误读为空，
        # 则改从 body 重新派生（锚点本就完全可由正文还原）。
        anchors = fm.get("anchors", [])
        if not anchors and body.strip():
            anchors = derive_anchors(body)
        # V2：id 由文件路径派生（不再有 id 列）；遗留 aliases/features 折叠进四要素 dict。
        person = _merge_legacy(fm.get("person"), fm.get("aliases"), fm.get("features"))
        return cls(
            id=os.path.splitext(os.path.basename(filepath or "unknown"))[0],
            title=fm.get("title", ""),
            summary=fm.get("summary", ""),
            tags=fm.get("tags", []),
            linked=fm.get("linked", []),
            person=person,
            location=_as_four(fm.get("location")),
            topic=_as_four(fm.get("topic")),
            event_date=fm.get("event_date", ""),
            anchors=anchors,
            created=fm.get("pkage_created") or fm.get("created", ""),
            updated=fm.get("pkage_updated") or fm.get("updated", ""),
            body=body.strip(),
        )

    @classmethod
    def from_markdown_fm_only(cls, text, filepath=None):
        """仅解析 front-matter 的轻量版，专供索引构建（rebuild / install）。

        索引不存正文（_upsert 不含 body 列），且 anchors 已随写入固化进
        front-matter，故跳过正文解析即可。返回 pkg；若 FM 缺 anchors（legacy
        包）则 anchors=[]，由调用方决定回退全量解析。
        """
        if not text.lstrip().startswith("---"):
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body="")
        lines = text.splitlines()
        if lines[0].strip() != "---":
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body="")
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            # FM 被截断（head 太小）或无结束符：交给调用方回退全量解析
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, anchors=[], body="")
        fm_text = "\n".join(lines[1:end])
        fm = cls._parse_fm(fm_text)
        person = _merge_legacy(fm.get("person"), fm.get("aliases"), fm.get("features"))
        return cls(
            id=os.path.splitext(os.path.basename(filepath or "unknown"))[0],
            title=fm.get("title", ""),
            summary=fm.get("summary", ""),
            tags=fm.get("tags", []),
            linked=fm.get("linked", []),
            person=person,
            location=_as_four(fm.get("location")),
            topic=_as_four(fm.get("topic")),
            event_date=fm.get("event_date", ""),
            anchors=fm.get("anchors", []),
            created=fm.get("pkage_created") or fm.get("created", ""),
            updated=fm.get("pkage_updated") or fm.get("updated", ""),
            body="",
        )

    @staticmethod
    def _strip_comment(s):
        """去掉行尾 YAML 风格注释 ` #...`（引号内的 # 保留）。"""
        out = []
        in_q = False
        for i, c in enumerate(s):
            if c == '"' and (i == 0 or s[i - 1] != '\\'):
                in_q = not in_q
            if c == '#' and not in_q and (i == 0 or s[i - 1] in ' \t'):
                break
            out.append(c)
        return "".join(out).rstrip()

    @staticmethod
    def _scalar_or_json(v):
        v = v.strip()
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            # block 模式引号值：严格 JSON 反转义，与单行 json.loads 行为对齐
            # （朴素去引号会丢失 \" 转义，导致含引号锚点 round-trip 不一致）。
            try:
                return json.loads(v)
            except Exception:
                return v[1:-1]
        if v and v[0] in "[{":
            try:
                return json.loads(v)
            except Exception:
                # 未引号中文列表（[维罗妮卡·夏·雪莱]）退回简易逗号切分，
                # 与 _parse_value 行为一致，避免 inline 列表被读成裸字符串。
                return EventPackage._parse_value(v)
        return v

    @staticmethod
    def _parse_value(v):
        # 简易列表/标量解析：兼容旧式未引号中文列表 [维罗妮卡·夏·雪莱]。
        v = v.strip()
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            return v[1:-1]
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            if not inner:
                return []
            out = []
            for it in inner.split(","):
                it = it.strip().strip('"').strip("'").strip()
                if it:
                    out.append(it)
            return out
        return v

    @staticmethod
    def _parse_inline(key, val):
        # 单行值：特殊字段优先 JSON（V2 字典/数组），失败回退简易列表解析。
        try:
            return json.loads(val)
        except Exception:
            return EventPackage._parse_value(val)

    @staticmethod
    def _is_kv(s):
        return ":" in s

    @staticmethod
    def _empty_default(key):
        if key in _FM_LIST:
            return []
        if key in _FM_DICT:
            return {}
        return ""

    @staticmethod
    def _parse_seq(items, start, indent):
        # 解析「- 项」列表；项可为标量，或「- key: val」起始的映射。
        seq = []
        i = start
        n = len(items)
        while i < n:
            ind, content = items[i]
            if ind < indent:
                break
            if ind > indent:
                i += 1
                continue
            if not content.startswith("- "):
                break
            body = content[2:].strip()
            if EventPackage._is_kv(body):
                # 映射项：首行 = body（在 indent），后续更深层归它
                sub = [(indent, body)]
                k = i + 1
                while k < n and items[k][0] > indent:
                    sub.append(items[k])
                    k += 1
                # 列表项的子键比「- 」深一级，需把首行重定基到子键缩进，
                # 否则 _parse_mapping 会把更深层子键当「超出 base」跳过。
                child_indent = min((it[0] for it in sub[1:]), default=indent)
                sub = [(child_indent, body)] + sub[1:]
                val, _ = EventPackage._parse_mapping(sub, 0, child_indent)
                seq.append(val)
                i = k
            else:
                seq.append(EventPackage._scalar_or_json(body))
                i += 1
        return seq, i

    @staticmethod
    def _parse_mapping(items, start, indent):
        # 解析「key: val」映射；val 可为单行值，或更深缩进的 block（列表/映射）。
        d = {}
        i = start
        n = len(items)
        while i < n:
            ind, content = items[i]
            if ind < indent:
                break
            if ind > indent:
                i += 1
                continue
            if ":" not in content:
                i += 1
                continue
            key, _, val = content.partition(":")
            key = key.strip()
            val = val.strip()
            if val:
                d[key] = EventPackage._scalar_or_json(val)
                i += 1
            else:
                k = i + 1
                sub = []
                while k < n and items[k][0] > indent:
                    sub.append(items[k])
                    k += 1
                if not sub:
                    d[key] = ""
                elif sub[0][1].startswith("- "):
                    v, _ = EventPackage._parse_seq(sub, 0, sub[0][0])
                    d[key] = v
                else:
                    v, _ = EventPackage._parse_mapping(sub, 0, sub[0][0])
                    d[key] = v
                i = k
        return d, i

    @staticmethod
    def _parse_node(items, start, indent):
        content = items[start][1]
        if content.startswith("- "):
            return EventPackage._parse_seq(items, start, indent)
        return EventPackage._parse_mapping(items, start, indent)

    @staticmethod
    def _normalize_anchor_kws(anchors):
        """锚点 keywords 归一化：若字段是「长得像 JSON 数组的字符串」（双编码
        畸形），解码为真列表；其余原样返回。覆盖 from_markdown / from_markdown_fm_only
        两条读取路径（二者共用 _parse_fm），使引擎与 block 序列化口径一致。"""
        if not isinstance(anchors, list):
            return anchors
        out = []
        for a in anchors:
            if not isinstance(a, dict):
                out.append(a)
                continue
            kw = a.get("keywords")
            if isinstance(kw, str):
                try:
                    dec = json.loads(kw)
                    if isinstance(dec, list):
                        kw = dec
                except Exception:
                    pass
            if isinstance(kw, list):
                a = dict(a)
                a["keywords"] = kw
            out.append(a)
        return out

    @staticmethod
    def _parse_fm(text):
        # 逐行 tokenize：去空行/全注释行，剥离行尾注释，记录缩进。
        items = []
        for ln in text.splitlines():
            if not ln.strip():
                continue
            if ln.lstrip().startswith("#"):
                continue
            ind = len(ln) - len(ln.lstrip(" "))
            content = EventPackage._strip_comment(ln.strip())
            if not content:
                continue
            items.append((ind, content))
        if not items:
            return {}
        base = min(ind for ind, _ in items)
        data = {}
        i = 0
        n = len(items)
        while i < n:
            ind, content = items[i]
            if ind != base:
                i += 1
                continue
            if ":" not in content:
                i += 1
                continue
            key, _, val = content.partition(":")
            key = key.strip()
            val = val.strip()
            if val:
                # 单行值（inline JSON 或裸标量）
                data[key] = (EventPackage._parse_inline(key, val)
                             if key in _FM_SPECIAL
                             else EventPackage._parse_value(val))
                i += 1
            else:
                # block 换行式：收集后续更深层行
                j = i + 1
                block = []
                while j < n and items[j][0] > base:
                    block.append(items[j])
                    j += 1
                if not block:
                    data[key] = EventPackage._empty_default(key)
                else:
                    v, _ = EventPackage._parse_node(block, 0, block[0][0])
                    data[key] = v
                i = j
        if "anchors" in data:
            data["anchors"] = EventPackage._normalize_anchor_kws(data["anchors"])
        return data


# ---------------------------------------------------------------------------
# 统一前台 db：仓库根 memory/ 下只有【一个】index.db
# ---------------------------------------------------------------------------
REPO_DIR_NAMES = ("memory", ".memory")   # R59 用户拍板去掉"."；.memory 留作旧库兼容


def _load_for_index(path):
    """索引构建专用加载：优先仅读 front-matter（省去正文 I/O 与解析）。

    返回 EventPackage；以下情况返回 None（调用方跳过该文件）：
      - 文件读失败 / 不存在（OSError）
      - 脚本派生视图（含 '本文件由脚本派生' 标记）
    正文不进索引（_upsert 不含 body 列），且 anchors 已随写入固化进
    front-matter，故默认跳过正文解析。若 FM 缺 anchors（legacy 包），
    回退 EventPackage.from_markdown 全量解析（从 body 派生），语义与改造前一致。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            # 读足够大的头部以覆盖含鸿篇巨制在内的几乎所有 front-matter（含长 anchors JSON）；
            # 1MB 上限可吞下《战争与和平》级（~360 章 / ~60KB anchors）的 FM 仍留 16x 余量；
            # 若 FM 仍超此上限致锚点 JSON 被截断，from_markdown_fm_only 会因
            # 找不到闭合 '---' 或解析失败回落到全量解析（_load_for_index 的
            # `if not pkg.anchors` 分支），不会索引到损坏的 anchors。
            head = f.read(1048576)   # 1MB：FM 读取上限（不读正文）
    except OSError:
        return None
    # 派生标记只检测文档开头（与 rebuild_index._auto_derive 的 _text[:600] 口径一致）：
    # 此前用全文 1MB 模糊匹配，会误判 design-journal 中在正文深处讨论「派生机制」
    # 的设计文档为派生文件而跳过（daylog设计/存储架构总览/拆包与收录规范 长期漏收）。
    if "本文件由脚本派生" in head[:600]:
        return None
    pkg = EventPackage.from_markdown_fm_only(head, path)
    if not pkg.anchors:
        # legacy 包 FM 无 anchors：全量解析（从 body 派生），保持原语义
        try:
            with open(path, "r", encoding="utf-8") as f:
                pkg = EventPackage.from_markdown(f.read(), path)
        except OSError:
            return None
    return pkg


def _repo_of(root):
    """从任意包目录向上找到 memory/（或旧式 .memory/）仓库根祖先。"""
    p = os.path.abspath(root)
    while True:
        if os.path.basename(p) in REPO_DIR_NAMES:
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return os.path.abspath(root)   # 找不到仓库根祖先：退化以 root 自身为仓
        p = parent


def _pkg_id(root, repo):
    """包标识 = 包目录相对仓库根的路径（如 原创角色/luzhao）。

    统一规范为【正斜杠】分隔——与用户心智模型、SKILL.md 示例
    （哲学/尼采、cache/archive）、跨平台一致。否则 Windows 会存成
    `哲学\尼采`（反斜杠），而用户/agent 传的是 `哲学/尼采`，
    精确匹配会静默失配。filepath 列仍存 OS 原生绝对路径
    （那是真实文件路径，非逻辑 id，不需要归一）。
    """
    r = os.path.abspath(root)
    rp = os.path.abspath(repo)
    if r == rp:
        return ""          # root 即仓库根：repo 级句柄（全局）
    return os.path.relpath(r, rp).replace(os.sep, "/")


# ---------------------------------------------------------------------------
# 内存存储：管理 memory/ 目录 + 统一 SQLite 薄索引
# ---------------------------------------------------------------------------

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


class Memory(MechanicalMixin):
    """混合记忆存储。

    统一前台 db（CEMA「前后台严格 1:1 铁律」的落地）：
    仓库根 memory/ 下只有【一个】index.db，所有事件包的索引都落在这张
    表里，用 package_id 列区分「属于哪个包」。每个事件包仍对应索引里
    恰好一条记录（id 唯一）——1:1 不变；package_id 只是把记录归到某包，
    便于「一个自动化脚本直接装卸某个记忆文件夹」（install/uninstall）。

    root 参数语义不变：仍是「某个包目录」（如 memory/原创角色/luzhao）；
    db 自动落在它的 memory/ 祖先下的 index.db，package_id 由 root 推出。
    """

    def __init__(self, root):
        self.root = root
        self.repo = _repo_of(root)
        self.db_path = os.path.join(self.repo, "index.db")
        self.package_id = _pkg_id(root, self.repo)
        # R50：移除 events/ 包装层，包目录即事件 .md 容器（双层级）
        self.events_dir = root
        os.makedirs(self.repo, exist_ok=True)        # 统一 db 所在目录
        os.makedirs(self.root, exist_ok=True)         # 包目录（写 .md 用）
        # 单例持久连接（autocommit），工具场景单线程，显式 close() 释放锁
        self._cx = None
        self._init_db()

    def close(self):
        """释放底层 SQLite 连接（删除/重建索引前调用）。"""
        if self._cx is not None:
            try:
                self._cx.close()
            except Exception:
                pass
            self._cx = None

    # ---- 索引层（SQLite 薄表，可由 front-matter 重建）--------------------
    def _conn(self):
        if self._cx is None:
            self._cx = sqlite3.connect(self.db_path, isolation_level=None)
            self._init_db()
        return self._cx

    def _init_db(self):
        """建 V2 索引表；若遇到旧表（含 id/aliases/features/created/updated 列）
        则原地迁移到 V2 结构（建新表→搬运→改名），幂等、可重复调用。"""
        # search_blob 填充态懒判定缓存（每 Memory 实例一次，见 _blob_populated 方法）。
        # 注意属性名不能与同名方法冲突（否则实例属性会遮蔽方法 → 调用报 NoneType
        # not callable），故命名为 _blob_populated_cache。必须在所有可能返回路径前
        # 初始化，否则 _blob_populated() 首访 AttributeError。
        self._blob_populated_cache = None
        c = self._conn()
        exists = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()
        if exists:
            cols = {r[1] for r in c.execute("PRAGMA table_info(events)").fetchall()}
            if "pkage_created" in cols:
                # 已是 V2 表：补 search_blob 列（旧库可能缺）+ 索引即返回
                if "search_blob" not in cols:
                    c.execute("ALTER TABLE events ADD COLUMN search_blob TEXT")
                c.execute("CREATE INDEX IF NOT EXISTS idx_pkg ON events(package_id)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_tags ON events(tags)")
                self._blob_ok = True   # 列已存在；旧行 NULL 由预筛 OR search_blob IS NULL 兜底
                # _blob_populated 已在 _init_db 顶部统一初始化为 None（此处不再重复）
                return
            # —— 旧表 → V2 迁移 ——
            c.execute("""
                CREATE TABLE events_v2 (
                    package_id TEXT, title TEXT, summary TEXT, tags TEXT,
                    linked TEXT, filepath TEXT, pkage_created TEXT,
                    pkage_updated TEXT, embedding BLOB, anchors TEXT,
                    person TEXT, event_date TEXT, location TEXT, topic TEXT,
                    search_blob TEXT,
                    PRIMARY KEY (package_id, filepath)
                )
            """)
            # 旧表可能缺部分新列，COALESCE 兜底空串；aliases/features 列数据由
            # rebuild 时 from_markdown 折叠进四要素 dict（不在此搬运）。
            c.execute("""
                INSERT OR REPLACE INTO events_v2
                    (package_id, title, summary, tags, linked, filepath,
                     pkage_created, pkage_updated, embedding, anchors,
                     person, event_date, location, topic)
                SELECT package_id, title, summary,
                       COALESCE(tags,''), COALESCE(linked,''), COALESCE(filepath,''),
                       COALESCE(created,''), COALESCE(updated,''), embedding,
                       COALESCE(anchors,''), COALESCE(person,''),
                       COALESCE(event_date,''), COALESCE(location,''), COALESCE(topic,'')
                FROM events
            """)
            c.execute("DROP TABLE events")
            c.execute("ALTER TABLE events_v2 RENAME TO events")
        else:
            c.execute("""
                CREATE TABLE events (
                    package_id TEXT, title TEXT, summary TEXT, tags TEXT,
                    linked TEXT, filepath TEXT, pkage_created TEXT,
                    pkage_updated TEXT, embedding BLOB, anchors TEXT,
                    person TEXT, event_date TEXT, location TEXT, topic TEXT,
                    search_blob TEXT,
                    PRIMARY KEY (package_id, filepath)
                )
            """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_pkg ON events(package_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tags ON events(tags)")
        # search_blob 预筛可用性：仅看列是否存在（PRAGMA O(列数)，不扫行）；
        # 行级 NULL 由预筛 SQL 的 "OR search_blob IS NULL" 兜底，无需每查询全扫。
        _cols = {r[1] for r in c.execute("PRAGMA table_info(events)").fetchall()}
        self._blob_ok = "search_blob" in _cols

    def _blob_filter(self, terms, ql):
        """返回 (SQL片段, params)：search_blob 子串预筛（OR 各 term + ql）。

        命中行必含会被 _anchor_score 子串得分的锚点（超集）→ 只 parse+打分候选行，
        把 O(总锚点)/查询 降到 O(命中行锚点)，零召回回归。
        `OR search_blob IS NULL` 兜底旧行（未 rebuild 填充）→ 绝不静默丢召回。"""
        parts, params = [], []
        for t in terms:
            if t:
                parts.append("search_blob LIKE ?")
                params.append("%" + str(t).lower() + "%")
        if ql:
            parts.append("search_blob LIKE ?")
            params.append("%" + str(ql).lower() + "%")
        if not parts:
            return "", []
        return "(" + " OR ".join(parts) + " OR search_blob IS NULL)", params

    def _blob_populated(self):
        """懒判定 search_blob 是否已【全行填充】。

        仅首次调用跑一次 O(行数) 的 count(*)（NULL 行数），结果缓存到
        self._blob_populated，后续直接命中缓存（零额外开销）。

        - True  ：所有行已填充（正常 rebuild 后的库）→ 三处 corpus SQL 函数
                  （_corpus_blob_candidates / _entity_in_corpus / _rare_entities）
                  可安全走 LIKE 快速路径；NULL 行不存在，不会漏命中→误拒答。
        - False ：仍有 NULL 行（旧库未 rebuild_all，search_blob 全空）→ 三处
                  函数退回逐文件 body 扫描兜底，绝不因 LIKE 漏 NULL 行而假拒答。

        关键区分：_score 的 _blob_filter 用「OR search_blob IS NULL」已天然兜底
        旧行（NULL 行仍进候选池），无需此判定；本方法仅服务于 LIKE『命中』语义的
        三处 corpus 函数——它们的 NULL 行会被 LIKE 静默排除，必须显式降级。

        为何不直接依赖 _blob_ok：_blob_ok 只看列是否存在（旧库 ALTER 后也 True），
        但列存在 ≠ 行已填充。旧库未 rebuild 时列全 NULL，若只判 _blob_ok 会误走
        快速路径并假拒答——故必须独立判定填充度。
        """
        if self._blob_populated_cache is not None:
            return self._blob_populated_cache
        c = self._conn()
        n_null = c.execute(
            "SELECT count(*) FROM events WHERE search_blob IS NULL"
        ).fetchone()[0]
        self._blob_populated_cache = (n_null == 0)
        return self._blob_populated_cache

    # ---- 写入路径（实时，Agent 直写 .md + 确定性 upsert 索引）-----------
    def write(self, id, title="", summary="", aliases=None, tags=None,
              linked=None, body="", created=None, updated=None,
              pkage_created=None, pkage_updated=None,
              anchors=None, embedding=None, trigger=None,
              person=None, location=None, topic=None, event_date=None,
              features=None, record_change=True, integrity_check=False,
              force_empty_body=False):
        """写/改一个事件包：原子写 .md + upsert 索引。
        anchors: 可选子事件锚点列表 [{Chapter, about, keywords}]（C+A 对象锚点，
        V2 形态，无 tags/locator），挂在同一个 .md 正文上，实现「1 个包 + 多锚点」
        的细粒度召回。
        trigger: 调用方标识（仅作元信息标签，当前不落任何变更日志；
                 历史曾用于 changes/ 快照审计，R59 续3 已废弃）。
        V2 注意：aliases / features 入参会被折叠进四要素 dict（person/location/topic），
        不再有独立存储列；时间用 pkage_created/pkage_updated（兼容旧 created/updated）。
        """
        created = pkage_created or created
        updated = pkage_updated or updated
        updated = updated or str(date.today())
        if anchors is None and body:
            anchors = derive_anchors(body)
        # 遗留 aliases/features 折叠进四要素（V2 无独立列）
        person = _merge_legacy(person, aliases, features)
        pkg = EventPackage(
            id=id, title=title, summary=summary,
            tags=tags or [], linked=linked or [],
            created=created, updated=updated, body=body,
            anchors=anchors,
            person=person, location=location, topic=topic, event_date=event_date,
        )
        # 若已存在且调用方未显式给 created，保留原 created（记录时间不变）；
        # 调用方显式传 created 时以调用方为准（如适配器写入收录时间）。
        existing = self.read(id)
        if existing and created is None:
            pkg.created = existing.created

        path = os.path.join(self.events_dir, f"{id}.md")
        # —— 护栏（R-safety）：禁止用空 body 覆盖有正文的既有文件 ——
        # 防止 memory_write / 任何调用方误传 body="" 把已落库正文清空
        # （历史上因此丢过设计期刊两篇文档正文）。确需清空请显式 force_empty_body=True。
        if os.path.exists(path) and not (body or "").strip() and not force_empty_body:
            try:
                _old = open(path, encoding="utf-8").read()
                _old_body = _old.split("---", 2)[-1] if _old.count("---") >= 2 else _old
            except OSError:
                _old_body = ""
            if _old_body.strip():
                raise ValueError(
                    "拒绝写入 %s：现有正文非空，但本次 body 为空。"
                    "若确要清空正文，请显式传 force_empty_body=True。"
                    % os.path.basename(path)
                )
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(pkg.to_markdown())
        os.replace(tmp, path)  # 原子落盘，崩溃安全

        self._upsert(pkg, path, embedding)
        # 写入侧反推（可选项，不阻断落库）：检测刚落库的实体是否缺独有弧段，
        # 返回 warning 清单供 Agent 侧反推用户补独有关键词。默认关闭以保持
        # write() 返回 path 的旧契约不变。
        if integrity_check:
            ek = _entity_key(title)
            warnings = self.check_write_integrity(target_ekeys={ek}, soft_k=3)
            return {"path": path, "warnings": warnings}
        return path

    def _upsert(self, pkg, path, embedding=None, package_id=None):
        pid = package_id if package_id is not None else self.package_id
        c = self._conn()
        c.execute("""
            INSERT INTO events
                (package_id,title,summary,tags,linked,filepath,
                 pkage_created,pkage_updated,embedding,anchors,
                 person,event_date,location,topic,search_blob)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(package_id, filepath) DO UPDATE SET
                title=excluded.title, summary=excluded.summary,
                tags=excluded.tags, linked=excluded.linked,
                filepath=excluded.filepath,
                pkage_updated=excluded.pkage_updated, embedding=excluded.embedding,
                anchors=excluded.anchors,
                person=excluded.person, event_date=excluded.event_date,
                location=excluded.location, topic=excluded.topic,
                search_blob=excluded.search_blob
        """, (
            pid, pkg.title, pkg.summary,
            json.dumps(pkg.tags, ensure_ascii=False),
            json.dumps(pkg.linked, ensure_ascii=False),
            path, pkg.created, pkg.updated,
            embedding,
            json.dumps(pkg.anchors, ensure_ascii=False),
            json.dumps(pkg.person, ensure_ascii=False),
            pkg.event_date,
            json.dumps(pkg.location, ensure_ascii=False),
            json.dumps(pkg.topic, ensure_ascii=False),
            _search_blob(pkg),
        ))

    # ---- 关联（单源：front-matter 为真相，索引为视图）--------------------
    def _write_back(self, pkg):
        """把「读改写」后的包写回其【原始目录】。

        R58 修复：link() 曾经统一走 self.write()，而 write() 硬编码落盘到
        self.events_dir（句柄根）。跨包 link 必须用全局 Memory("memory")
        句柄解析 id，于是两个端点被"搬家"到 memory/ 根，产生
        package_id='' 的重复包体。现按 pkg.path（read 回填的来源路径）
        为目标目录开局部句柄写回，文件永远留在原位。
        """
        dst_dir = os.path.dirname(pkg.path) if pkg.path else self.events_dir
        same = os.path.abspath(dst_dir) == os.path.abspath(self.events_dir)
        m = self if same else Memory(dst_dir)
        try:
            # 保留读取到的全部字段原样写回（含锚点/四要素），不重派生、不丢字段。
            # 仅当锚点为空/缺失时才令 write() 从 body 重新派生。
            # 避免 link() 把对话记录刻意设的单一整体锚点 ["对话记录"] 覆盖成多段派生锚点
            # （query_anchors 会双计同包），以及把 person/event_date/location/topic 清空。
            m.write(pkg.id, pkg.title, pkg.summary, tags=pkg.tags,
                    linked=pkg.linked, body=pkg.body, created=pkg.created,
                    updated=pkg.updated,
                    anchors=pkg.anchors if pkg.anchors else None,
                    person=pkg.person, location=pkg.location,
                    topic=pkg.topic, event_date=pkg.event_date)
        finally:
            if m is not self:
                m.close()

    def link(self, id_a, id_b):
        """双向关联两个事件包：更新两者 front-matter 的 linked。
        每个端点写回各自原始目录（见 _write_back），跨包 link 不再搬家。"""
        a = self.read(id_a)
        b = self.read(id_b)
        if not a or not b:
            missing = [x for x, p in ((id_a, a), (id_b, b)) if not p]
            raise ValueError(f"事件包不存在: {missing}")
        if id_b not in a.linked:
            a.linked.append(id_b)
        if id_a not in b.linked:
            b.linked.append(id_a)
        self._write_back(a)
        self._write_back(b)

    # ---- 检索路径（确定性、无状态、O(n) 全表扫描）-------------------------
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
        # 中文复合查询修复（缺口 A）：normalize_terms 只按空白切词，中文无空格
        # → 整句成一词 → 复合中文查询（如「会议和产品需求文档都讲了什么」）全失配。
        # 含中文时用 _reform_terms 做 CJK 整词+二元切分（与 query_anchors 同口径），
        # 拆出「会议/产品需求文档/讲…」各自命中，与 L2 锚点级检索对齐。
        if re.search(r"[一-鿿]", ql):
            ql = " ".join(_reform_terms(ql))
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
            aliases = _flat_variants(pj) + _flat_variants(tj) + _flat_variants(lj)
            tags = json.loads(tags_j or "[]")
            s = self._score(ql, rid, title, summary, aliases, tags)
            if s > 0:
                scored.append((rid, title, summary, s, updated, edate))

        # 确定性排序：分数降序 → 事件时间近因 tie-break（无事件时间则退化写入时间）→ id 升序。
        # 机制A：仅在分数相等的候选间用事件时间裁决先后（不破 §13 反遗忘；全量时间重排会
        # 把 daylog 顺带提及的低相关新条目顶到旧高相关条目前，故只做平局裁决）。
        scored.sort(key=lambda x: (-x[3], _time_tiebreak(x[5], x[4]), x[0]))
        return [(x[0], x[1], x[2], x[3]) for x in scored[:top_k]]

    # ---- 召回消歧：歧义门 + 特征判别澄清（实体歧义由本方法承担）-----------
    def _entity_feature_index(self, package_id=None):
        """构建实体特征索引 {ekey: {"features":{token:tier}, "title":..., "rids":[...]}}。

        复用生产四要素约定：person/topic/location 为 {canonical:[variants]} dict，
        anchors 为 [{Chapter, about, keywords}]；仅结构化维度计入判别特征，
        title/summary/about/chapter 等自由文本排除（粒度太粗会伪造独特性）。
        实体按 _entity_key(title) 去重，多行/多分章归并为一个实体。
        """
        c = self._conn()
        if package_id:
            rows = c.execute(
                "SELECT filepath,title,summary,tags,person,topic,location,anchors "
                "FROM events WHERE package_id=? OR package_id LIKE ? || '/%'",
                (package_id, package_id)).fetchall()
        else:
            rows = c.execute(
                "SELECT filepath,title,summary,tags,person,topic,location,anchors "
                "FROM events").fetchall()
        idx = {}
        for fp, title, summary, tags_j, pj, tj, lj, aj in rows:
            ek = _entity_key(title)
            ent = idx.setdefault(ek, {"features": {}, "title": title, "rids": []})
            ent["rids"].append(os.path.splitext(os.path.basename(fp))[0])
            feats = ent["features"]
            for raw, ftype in ((pj, "person"), (tj, "topic"), (lj, "location")):
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    parsed = None
                d = _as_four(parsed)
                tier = _FIELD_TIER.get(ftype, 0)
                for canon, variants in d.items():
                    for tok in ([canon] + list(variants or [])):
                        tk = _norm(tok)
                        if len(tk) >= 2 and (tk not in feats or tier > feats[tk]):
                            feats[tk] = tier
            try:
                for tg in json.loads(tags_j or "[]"):
                    tk = _norm(tg)
                    if len(tk) >= 2:
                        tier = _FIELD_TIER["tags"]
                        if tk not in feats or tier > feats[tk]:
                            feats[tk] = tier
            except Exception:
                pass
            try:
                for a in json.loads(aj or "[]"):
                    if not isinstance(a, dict):
                        continue
                    for kw in (a.get("keywords") or a.get("tags") or []):
                        tk = _norm(kw)
                        if len(tk) >= 2:
                            tier = _FIELD_TIER["kw"]
                            if tk not in feats or tier > feats[tk]:
                                feats[tk] = tier
            except Exception:
                pass
        return idx

    def _neg_features_from_query(self, q, idx):
        """从查询抽否定子句（「不是X」→ 排除带 X 特征的实体）。

        启发式：定位否定标记后的子句，从索引全部特征里挑出与子句双向子串相关的 token。
        生产环境应换 LLM 精准解析否定意图（同 resolve_query 管线可插拔）。"""
        _NEG_MARKERS = ("不是", "排除", "除了", "非", "别是", "不要", "而非")
        ql = _norm(q)
        for marker in _NEG_MARKERS:
            if marker in ql:
                clause = ql.split(marker, 1)[1]
                negs = set()
                for ent in idx.values():
                    for tok in ent["features"]:
                        if len(tok) >= 2 and (tok in clause or clause in tok):
                            negs.add(tok)
                return negs
        return set()

    def _anchor_only_tokens(self):
        """全局『仅出现在锚点 keywords、不在任何结构化字段(person/topic/location)』的 token 集。

        这些 token 是实体正文里顺带提到的共现词（如故事里出现的配角名 娜塔莎/弗瑞），
        不是该实体自身的判别特征。澄清『独有弧段』应排除它们，只亮实体自己的特征。
        结构化特征口径与 _entity_feature_index 一致：person/topic/location 的规范名 + 变体。"""
        c = self._conn()
        structured, anchor = set(), set()
        for fp, pj, tj, lj, aj in c.execute(
                "SELECT filepath, person, topic, location, anchors FROM events"):
            for raw in (pj, tj, lj):
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    parsed = None
                d = _as_four(parsed)
                for canon, variants in d.items():
                    for tok in ([canon] + list(variants or [])):
                        tk = _norm(tok)
                        if len(tk) >= 2:
                            structured.add(tk)
            try:
                for a in json.loads(aj or "[]"):
                    if not isinstance(a, dict):
                        continue
                    for kw in (a.get("keywords") or a.get("tags") or []):
                        tk = _norm(kw)
                        if len(tk) >= 2:
                            anchor.add(tk)
            except Exception:
                pass
        return anchor - structured

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
        # （如故事里顺带提到的配角名 娜塔莎/弗瑞）——它们不是实体自身特征，
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

    # ---- 覆盖门（软·强信号快捷通道）---------------------------------------
    def _query_tokens(self, q, keywords=None, decomposer=None):
        """覆盖门用的查询 token：与召回同源。
        - keywords 来自理解层（AI 路径）→ 直接采用。
        - decomposer 注入 → 取其分解结果。
        - 否则按 '+'/空白 切分（AIMH 特征词查询形态：蓝+钻石 / 孤品 蓝钻）。
        不做 CJK 二元扩展：保持与沙箱原型一致的『连续子串』匹配语义，
        避免 '纯蓝' 误命中 '纯净蓝'（净在中间非连续）导致 paraphrase 被误判为区分词。
        """
        if keywords is not None:
            toks = [str(k).strip() for k in keywords if str(k).strip()]
        elif callable(decomposer):
            dq = decomposer(self, q) or ""
            toks = [t for t in re.split(r'[+\s]+', dq) if t]
        else:
            toks = [t for t in re.split(r'[+\s]+', q.strip()) if t]
        out, seen = [], set()
        for t in toks:
            tl = t.lower()
            if tl and tl not in seen:
                seen.add(tl)
                out.append(tl)
        return out

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
                from .refine import corpus_overlap_absent
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
            return {"decision": "return", "results": results[:top_k],
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
                    "results": [(r[0], r[1], r[2], r[3]) for r in distinct][:top_k],
                    "stage": "keyword", "ambiguous": False}

        idx = self._entity_feature_index(package_id)
        cands = [(r[0], r[1], r[2], r[3]) for r in distinct if _entity_key(r[1]) in idx]
        if len(cands) < MIN_CANDIDATES:
            return {"decision": "return",
                    "results": [(r[0], r[1], r[2], r[3]) for r in distinct][:top_k],
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

    # ---- 写入侧反推：落库完整性检查（检测缺独有弧段的实体）---------------
    def _missing_unique_arcs(self, idx, global_count, target_ekeys, soft_k=3):
        """检测缺乏独有弧段的实体（写入侧反推的核心计算）。

        判据（修正文档中 G(e) 的提法：严格独有弧 global_count==1 故 G(e) 恒为 1，
        软缺失改用『共有邻居数』share_count 衡量拥挤度）：
          · 实体无任何结构化特征（F(e)=∅）→ 跳过（惰性实体，非歧义风险）。
          · 硬缺失：F(e)≠∅ 且 unique_arcs（global_count==1）为空 → 全部特征被其他
            实体共享，任何命中它的查询必落多圆交集、必触发歧义门。
          · 软缺失：有独有弧但 share_count≥soft_k → 处于拥挤邻域，建议补更具体关键词。
        idx / global_count 必须由调用方基于『全局』实体特征索引构建（唯一性能否成立
        须相对全部实体判定，不能只在单包内看）。target_ekeys=None 评估全部实体。
        返回 [{ekey,title,severity,unique_arcs,share_count,suggest}]。
        """
        if target_ekeys is None:
            target_ekeys = set(idx.keys())
        warnings = []
        for ek in target_ekeys:
            if ek not in idx:
                continue
            F = idx[ek]["features"]
            if not F:
                continue  # 惰性实体：无结构化特征，非歧义风险，不误报
            unique = [f for f in F if global_count.get(f, 9999) == 1]
            # 共有邻居：与 e 共享≥1 特征的其它实体数（O(E·F)，个人记忆规模可忽略）
            co = 0
            Fset = set(F)
            for o, oent in idx.items():
                if o == ek:
                    continue
                if Fset & set(oent["features"]):
                    co += 1
            if not unique:
                severity = "hard"
            elif co >= soft_k:
                severity = "soft"
            else:
                continue
            reason = ("没有任何独有特征，召回极易与其它实体混淆"
                      if not unique else f"处于拥挤邻域（与 {co} 个实体共享特征）")
            suggest = (f"「{idx[ek]['title']}」{reason}；请给它一个别处用不到的独有关键词"
                       f"（某条独有属性 / 代号 / 场景），写入 person/location/topic 规范名变体"
                       f"或锚点 keywords，使其获得至少一条 global_count==1 的独有弧段。")
            warnings.append({
                "ekey": ek,
                "title": idx[ek]["title"],
                "severity": severity,
                "unique_arcs": unique,
                "share_count": co,
                "suggest": suggest,
            })
        return warnings

    def check_write_integrity(self, target_ekeys=None, soft_k=3):
        """写入侧反推入口：检测缺乏独有弧段的实体（落库前/后均可调用，不阻断写入）。

        target_ekeys=None → 扫描全部实体（lint 模式，可批量体检记忆库）；
        传具体 ekey 集合（如刚落库包 title 的 _entity_key）→ 只查那一个。
        始终基于『全局』实体特征索引判定唯一性。返回 warning 列表（见 _missing_unique_arcs）。
        """
        idx = self._entity_feature_index()  # 全局
        global_count = {}
        for ent in idx.values():
            for f in ent["features"]:
                global_count[f] = global_count.get(f, 0) + 1
        return self._missing_unique_arcs(idx, global_count, target_ekeys, soft_k)

    # ---- IDF 权重（完全可由 index.db 重建，不引入新持久状态）-------------
    def _build_idf(self):
        """懒构建文档频率表。

        文档 = 单个事件包「全部锚点的 title+summary+body+tags 拼成的一段」。
        df(t) = 含 t（子串）的包数；idf = log((N+1)/(df+1)) + 1，N 为包总数。
        该统计只读 index.db，可随时由 front-matter 重建，故不落盘缓存。
        """
        c = self._conn()
        docs = []
        for rid, aj in c.execute("SELECT filepath,anchors FROM events").fetchall():
            try:
                anchors = json.loads(aj or "[]")
            except Exception:
                anchors = []
            parts = []
            for a in anchors:
                if not isinstance(a, dict):
                    continue
                parts.append((a.get("title") or a.get("Chapter") or ""))
                parts.append((a.get("about") or a.get("summary") or ""))
                parts.append(self._anchor_body(rid, a))
                for tg in (a.get("tags") or a.get("keywords") or []):
                    parts.append(tg)
            docs.append(" ".join(parts).lower())
        self._idf_docs = docs
        self._idf_df = {}
        self._idf_N = len(docs)

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

    def _pkg_freq(self, t):
        """term t 在多少个「包」中出现（子串匹配；文档=单包全部锚点拼合文本，
        与 _build_idf 同口径、复用其懒构建结果）。供 grounding 反向门限用：
        跨包越常见→越非判别→越不该被注入成检索词。t 为空返回 0。"""
        if getattr(self, "_idf_docs", None) is None:
            self._build_idf()
        t = (t or "").lower()
        if not t:
            return 0
        return sum(1 for d in self._idf_docs if t in d)

    # ---- 确定性 BM25 重排（query_anchors 的 rerank=True 模式）---------------
    # 无向量、可由正文重建，对应 HMA 理解层/L2 的排序职责。
    # 实测把 hit@5 从 89.7% 提到 ~92%、hit@1 从 60% 提到 ~72%
    # （LoCoMo 1982 题，reform+idf+pkgagg 配置下）。
    _RERANK_TOK = re.compile(r"[A-Za-z0-9]+|[一-鿿]")
    _RERANK_K1 = 1.5
    _RERANK_B = 0.75
    _RERANK_COV_W = 6.0

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

        return sorted(scored, key=lambda e: (-score(e), e[0], e[1]))


    def _kw_index(self):
        """结构性关键词→包索引（关键词补齐用），从 DB 各包锚点 keywords 派生。

        非手写：随语料自动更新，新包进仓库即获得判别力。缓存于实例（rebuild
        后失效：调用方重新构造 Memory 即可）。返回 {keyword(lower): set(package_id)}。
        """
        if getattr(self, "_kw_index_cache", None) is None:
            idx: Dict[str, Set[str]] = {}
            c = self._conn()
            for pid, aj in c.execute("SELECT package_id, anchors FROM events"):
                try:
                    anchors = json.loads(aj or "[]")
                except Exception:
                    anchors = []
                for a in anchors:
                    if not isinstance(a, dict):
                        continue
                    for kw in (a.get("keywords") or []):
                        if kw:
                            idx.setdefault(str(kw).lower(), set()).add(pid)
            self._kw_index_cache = idx
        return self._kw_index_cache

    def query_anchors(self, q, top_k=5, package_id=None, dedup_packages=False,
                      idf=True, package_agg=False, rerank=True, reform=True,
                      use_field_weights=True, use_features=False,
                      allow_abstain=False, kappa=None,
                      context=None, decomposer=None, keywords=None, scope=None):
        """细粒度召回：在锚点层检索，返回命中的子事件。
        返回 [(pkg_id, anchor_title, anchor_about, locator, score), ...]（anchor_about = 锚点 about 字段，summary 仅兼容回退）。
        用于「1 个包 + 多锚点」场景下的精准故事召回。
        package_id 过滤语义同 query。

        dedup_packages=True → 每个事件包最多保留得分最高的一个锚点。
        默认 False，保留「同包多锚点」的精准段落召回（Veronica 类用法）；
        跨包广检索（想让 top_k 覆盖 k 个不同事件）时才置 True。

        reform=True（默认开）→ 先经「理解层 L1.5」把自然语言问句压成规范关键词，
        再做确定性匹配。默认理解层 = self._understand_query（零-ML）：四要素字段
        grounding（问句/context 命中本仓 person/topic/event_date/location 的规范名
        或变体，即把规范名当检索词，变体提问也能接地）+ _reform_terms 内容词兜底
        （CJK 二元 + 英文去噪）。无模型、可由正文重建，对应 HMA 理解层/L2 的查询
        分解职责。等价于 locomo_bench.reform() 的确定性部分。

        decomposer= 可注入调用方提供的理解层（如 LLM 语义分解）：传入 callable
        时，reform=True 改为调用 decomposer(self, q, context=context) 取关键词，
        引擎自身绝不调用任何模型（保持零-ML 契约）；不传则用默认确定性理解层。

        keywords= 是**最直截的真·功能接口**：AI 理解层先把自然语言问句解析成
        规范实体词列表，直接经此参数传入（优先级高于 decomposer 与机械拆词）。
        这是「AI 负责理解、引擎负责确定性检索与拒答」契约的落点；无 AI 接线时
        才退化到 _understand_query 的机械 CJK 二元兜底，不靠它硬顶召回/拒答。

        idf=True（默认开）→ 逐词计分乘以该词的 IDF 权重（稀有词权重高、常见
        词权重低），削弱 "the/when/did" 这类处处都有的功能词把判别词信号淹没。

        package_agg=False（默认关）→ 把同一事件包下所有锚点分数求和后只留
        每包一条（取包内得分最高锚点作代表）。用于「跨包广检索」时，让证据
        分散在多个锚点的包不被单段计分压低；与 dedup_packages 互斥（本模式
        已天然每包一条）。默认关闭是为了保留「同包多锚点精准召回」
        （Veronica/OC 类单包多锚点用法）；跨包广检索（LoCoMo bench）显式开启。

        rerank=True（默认开）→ 在已捞到的候选（完整候选池，与 top_k 无关）
        上做一层确定性 BM25 重排（含词项覆盖奖励；无向量、可由正文重建），
        把「含全部查询词却被弱判别信号压制的 gold 包」顶回前排。对应 HMA
        理解层/L2 的排序职责。rerank 采用 OR-fail-safe：重排后只许用更优
        候选替换 top_k 里的「非答案」占位，绝不把 base 已进 top_k 的锚点
        （可能正是 gold）挤出——直接实现「顶掉非答案、保住答案」。

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
            # 机械拆词(_understand_query) 仅在没有 AI 接线时的兜底，不靠它硬顶。
            # 归一小写：下游 _anchor_score / _apply_field_weights / _coverage /
            # _corpus_top_term_hit_files 全按小写匹配（锚点文本与四要素字段已
            # .lower()），AI 传入原大小写关键词会致子串匹配全失（如 "CEMA"
            # 命中不了小写 "cema" → 0 召回）。机械路径能命中，是因
            # _understand_query 额外产出小写变体；此处直接归一，省去变体依赖。
            terms = [str(k).lower() for k in keywords]
            ql = " ".join(terms) if terms else q.lower().strip()
        elif reform:
            if callable(decomposer):
                # 调用方注入的理解层（如 LLM 语义分解）。引擎零-ML：此路径由
                # agent shell 提供，引擎自身绝不调用任何模型。
                terms = decomposer(self, q, context=context) or []
            else:
                # 默认确定性理解层（L1.5）：四要素 grounding + 内容词兜底。
                terms = self._understand_query(q, context=context)
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
        # ② 检索策略：**别名硬锁 + 全局先捞全 + 伞包降权**。
        # 自动路由 resolve_scope 返回 (scope_pid, confident)：
        #   - confident=True（仅命中① SUBJECT_SCOPE 别名：hma/cema/veronica 等）→
        #     把候选池**硬锁**到该包（窄池、快、无伞包噪声，且别名无碰撞故不误锁）；
        #   - confident=False（② 关键词补齐 / ③ 目录名·标题弱匹配，泛词易碰撞）→
        #     **退全库检索**，由下游伞包降权兜底，谁都不预先排除（修 T08/T12 误锁、
        #     T08 误锁 demo 包）。关键词补齐是软信号（仅 +4 加权、绝不硬锁），因锚点
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
            sql = (
                "SELECT filepath,title,anchors FROM events "
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
            sql = "SELECT filepath,title,anchors FROM events"
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
        def _score(tlist):
            # idf 权重逐词预计算一次（置于 terms 循环外），避免逐锚点重复构造字典
            w = {t: (self._idf(t) if idf else 1.0) for t in tlist}
            out = []
            for rid, doc_title, anchors_j in rows:
                doc_title_l = (doc_title or "").lower()
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
            base_top = scored[:top_k]          # 重排前已排序好的 top_k（常含 gold）
            rerank_sorted = self._rerank(scored, ql, pid)
            # OR-fail-safe：重排只许用更优候选「升级」排序，绝不可把 base 已进
            # top_k 的锚点（可能正是 gold）挤出窗口。保护粒度必须是「锚点级」
            # (e[0],e[1]) 而非「包级」e[0]——否则同包多锚点时，rerank 若只保留了
            # 该包的某个锚，另一个 base_top 锚点（可能是 base_top[0] 即最高分锚）
            # 会被误判「该包已在场」而遭丢弃，进而使 rule#1 找不到它、gold 漏出。
            # 实现：以重排结果为底，若某 base_top 锚点被重排挤出 top_k，则用
            # 「顶掉一个非 base_top 锚点」的方式把它插回，保证 base_top 锚点永不丢失。
            final = list(rerank_sorted[:top_k])
            base_anchor_ids = {(e[0], e[1]) for e in base_top}
            present = {(e[0], e[1]) for e in final}
            for e in base_top:
                if (e[0], e[1]) in present:
                    continue
                # 找 final 里一个非 base_top 锚点顶掉（从尾部优先）
                dropped = False
                for i in range(len(final) - 1, -1, -1):
                    if (final[i][0], final[i][1]) not in base_anchor_ids:
                        final.pop(i)
                        dropped = True
                        break
                if not dropped:
                    final.pop()  # 兜底：全是 base_top 锚点时顶掉最后一个
                final.append(e)
                present.add((e[0], e[1]))
            scored = final
        # 守 #1（防 BM25 长文档惩罚把原始分明显领先的精确答案压到次位）：
        # 原始分最高的 base_top[0]（锚点级）必须居首；若被 rerank 翻到次位（无论
        # 仅包相同但锚点不同，还是包都不同），移回首位。与上方 OR-fail-safe 同用
        # 锚点级身份 (e[0],e[1]) 判定，避免同包多锚点场景下最高分锚被埋。
        if rerank and base_top and scored and (
                base_top[0][0] != scored[0][0] or base_top[0][1] != scored[0][1]):
            idx = next((i for i, e in enumerate(scored)
                        if e[0] == base_top[0][0] and e[1] == base_top[0][1]), None)
            if idx is not None:
                scored.pop(idx)
                scored.insert(0, base_top[0])
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
            # 守 #1（body-aware rerank 后再钉一次）：密度重排会把 BM25 最高分锚
            # （常为 gold）翻离首位，这里钉回 #1。与上方 rule#1 同锚点级身份判定，
            # 仅把【已存在于答案里】的 base_top[0] 移到首位、不动 top_k 集合，故不
            # 损伤已由 rerank 抬进窗口的 body-only 事实（recall@5 保底）。
            if rerank and base_top:
                bt0 = base_top[0]
                bt0_stem = os.path.splitext(os.path.basename(bt0[0]))[0]
                idx = next((i for i, e in enumerate(ans)
                            if e[0] == bt0_stem and e[1] == bt0[1]), None)
                if idx is not None and idx != 0:
                    ans.insert(0, ans.pop(idx))
            res["answer"] = ans
            return res
        return [_stemify(r) for r in scored[:top_k]]

    # ---- 拒答层（faithfulness gate，确定性、零 ML）---------------------------
    def _pkg_body(self, rid):
        """单包正文（小写），供 Gate1 覆盖度复用 _anchor_score 的实际打分字段。

        正文只存 .md（events 表无 body 列），故走 read_body 从文件取。
        """
        b = self.read_body(rid)
        return (b or "").lower()



    def _pkg_fields(self, rid, pid=None):
        """单包四要素字段集合（小写），供 Gate2 命中判定。

        rid 内部为文件名 stem（V2 检索契约）；filepath 列存完整路径，
        故按 stem 模糊匹配。pid 限定包作用域——query_anchors 已按包缩圈，
        必须沿用同一作用域，否则同名 stem（如 demo 包与正式包都叫
        veronica-origin）会被跨包误判，导致正确实体被错拒。
        """
        c = self._conn()
        if rid.endswith(".md"):
            q = "SELECT person,location,topic,event_date FROM events WHERE filepath=?"
            params = (rid,)
        else:
            q = ("SELECT person,location,topic,event_date FROM events "
                 "WHERE (filepath LIKE ? OR filepath LIKE ?)")
            params = ("%/" + rid + ".md", "%\\" + rid + ".md")
        if pid:
            q += " AND package_id=?"
            params = params + (pid,)
        rows = c.execute(q, params).fetchall()
        if not rows:
            return set()
        s = set()
        for p, loc, top, d in rows:
            for fld in (p, loc, top):
                for v in _flat_variants(fld):
                    if v:
                        s.add(str(v).lower())
            if d:
                s.add(str(d).lower())
        return s

    def _out_of_scope(self, q, scored, pid=None):
        """Gate2：查询解析出已知四要素实体，但召回包「四要素 + 正文」零命中 → 越界拒答。

        忠实落地用户设计的「基准真机制=四要素字段缩圈」：当前 query_anchors
        只把四要素当 rerank 裁判（_apply_field_weights），从不缩圈；此闸让越界
        查询真正被拒。零 ML（对全库实体词表做字典命中）。未知实体（不在词表）
        则交 Gate1 覆盖度判定（即用户设计的「topic 未规范则缩圈静默漏」边界）。

        命中口径须与 _coverage/_anchor_score 一致（title+about+tags+body）：
        实体只要出现在召回包的正文里，即视为「在包内」，不被四要素硬闸误拒——
        否则会出现「body 命中、about 未命中」的正确召回被过度拒答
        （Veronica 实测 5/9 过度拒答即此因；如代号「黑寡妇」仅在正文出现、
        未进结构化 person 变体时不应被错拒）。
        """
        vocab = self._entity_vocab()
        if not vocab:
            return False
        ql = str(q).lower()
        resolved = {e for e in vocab if e and e in ql}
        if not resolved:
            return False
        for rid in {s[0] for s in scored}:
            if self._pkg_fields(rid, pid) & resolved:
                return False
            # 正文命中同样算「在包内」（与 _coverage 同口径）
            body = self._pkg_body(rid)
            if body and any(e in body for e in resolved):
                return False
        return True

    def _corpus_files(self, pid=None):
        """作用域内全部 .md 的 filepath（与 query_anchors 同 scope）。

        pid 非空 → package_id=? OR package_id LIKE pid||'/%'；pid 空 → 全库。
        供 Gate1 语料包含性校验做全量正文扫描。
        """
        c = self._conn()
        if pid:
            rows = c.execute(
                "SELECT DISTINCT filepath FROM events "
                "WHERE package_id=? OR package_id LIKE ? || '/%'",
                (pid, pid)).fetchall()
        else:
            rows = c.execute("SELECT DISTINCT filepath FROM events").fetchall()
        return [r[0] for r in rows if r[0]]

    # 语料包含性拒答的「干净实体」过滤：剥离问句壳（疑问/功能字）与跨域通用词，
    # 只认能代表问题的专有实体/概念词。避免「作者/价格/怎么」等跨域词把域外问题
    # 误判为领域内（如「红楼梦的作者是谁」中"作者"在库却非实体 → 仍拒答）。
    _FUNCTIONAL_CHARS = set(
        "谁什么怎么怎样哪几多是的吗呢为何如何多少干嘛啥"
        "有系颗行阳太币格价今作"
    )
    _GENERIC_TERMS = {
        "作者", "价格", "做法", "意思", "定义", "名字", "时间", "地方", "类型",
        "方式", "原因", "作用", "内容", "方法", "过程", "问题", "情况", "事情",
        "东西", "部分", "为什么", "何处", "干嘛", "多少", "怎么",
        # 查询状态/时间副词：非内容实体，与「时间/情况」同类，从判别实体剔除，
        # 避免域外问题（量子计算/苹果股价）靠「最新/进展/股价」等通用碎片误判语料有。
        "最新", "进展", "新进", "股价", "目前", "当前", "更新", "近日", "近来",
        "此前", "当时", "如今", "关于", "方面",
    }

    def _apply_field_weights(self, scored, q, terms, route_target=None):
        """理解层四要素软加权 + 查询→包路由（post-retrieval rerank，零 ML）。

        对每条候选按「命中的结构化要素数」加权（时间/地点/人物/主题四要素 +
        包级 tags），命中越多越靠前，但**不剔除任何候选**——只调序。语义是
        「结构化约束缩小候选 + 文本精排」的软版：检索器本身仍从原始文本捞出候选，
        四要素只当「排序裁判」，故不构成对 HMA 零-ML 纯文本检索契约的稀释。

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
                bonus += 100
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

    def query_two_hop(self, q, top_k=5, min_hit=2):
        """两跳检索（用户订正后的正确流程，权威路径）：

        跳1（L1.5 归一）：用 query_features 的特征重叠，把查询的【表面变体】
              锁定到 canonical 精准词（如「黄蓝色宝石」→「圣保罗之焰」）。
              features 在这里只干一件事：归一。不做召回。
        跳2（L2 全文）：拿锁定到的 canonical 词，走【既有全文检索】
              query_anchors(canon) 取精准段落。召回仍归全文检索，
              不另起炉灶。

        返回 (locked, searched)：
          locked   = query_features 锁定的候选 [(pid,canon,reason,score)]
          searched = 每个锁定 canonical 的全文检索结果
                     [(pid,canon,reason,anchor_hits)]
        """
        locked = self.query_features(q, top_k=top_k, min_hit=min_hit)
        searched = []
        for pid, canon, reason, score in locked:
            hits = self.query_anchors(canon, top_k=top_k)
            searched.append((pid, canon, reason, hits))
        return locked, searched

    # ---- 多跳召回：沿 linked 双向 BFS 扩簇（V1.0 生产化）-------------------
    def _linked_adjacency(self):
        """从 events.linked 建无向邻接表 {filepath: set(filepath)}。

        linked 存复合 id（如 `项目/AIMH-design-journal/xxx.md`，可能带/不带
        `memory/` 前缀，或仅写 stem）。解析时按「后缀匹配 filepath」兜底，
        解析不到的悬空 id 直接丢弃（不报错）。双向：link() 已双写，此处仍按
        边并集处理，兼容旧/部分 link。零 ML、可由 index.db 重建。
        """
        c = self._conn()
        rows = c.execute("SELECT filepath, linked FROM events").fetchall()
        fps = [fp for fp, _ in rows]
        fp_index = {fp.replace("\\", "/"): fp for fp in fps}

        def resolve(lid):
            if not lid:
                return None
            lid_n = lid.replace("\\", "/").lstrip("/")
            for key, fp in fp_index.items():      # 1) 后缀匹配（兼容 memory/ 前缀）
                if key.endswith("/" + lid_n) or key == lid_n:
                    return fp
            stem = os.path.splitext(os.path.basename(lid))[0]   # 2) stem 匹配
            for fp in fps:
                if os.path.splitext(os.path.basename(fp))[0] == stem:
                    return fp
            return None

        adj = {fp: set() for fp in fps}
        for fp, lj in rows:
            try:
                links = json.loads(lj or "[]") or []
            except Exception:
                links = []
            for lid in links:
                r = resolve(lid)
                if r and r != fp:
                    adj[fp].add(r)
                    adj[r].add(fp)                # 双向
        return adj

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
                score += 1_000_000.0
            out.append((rid, title, summary, score, hop))
        # 排序：链接相关度（final score，含命名 boost）优先，hop 仅作 tiebreak，
        # 末位用 rid 字符串兜底 → 完全确定（消除 run-to-run 漂移）。
        out.sort(key=lambda x: (-x[3], x[4], x[0]))
        return [(r[0], r[1], r[2], r[3]) for r in out[:top_k]]


    @staticmethod
    def _score(ql, rid, title, summary, aliases, tags):
        # 与 query_anchors 同口径：剥标点、滤英文功能词；CJK 无空格则整体一词
        terms = normalize_terms(ql)
        if not terms:
            return 0
        rid_l = rid.lower()
        title_l = (title or "").lower()
        sum_l = (summary or "").lower()
        tags_l = [t.lower() for t in tags]
        aliases_l = [a.lower() for a in aliases]

        s = 0
        # id 命中
        if ql == rid_l:
            s += 100
        elif any(t in rid_l for t in terms):
            s += 30
        # title 命中（整串精确 > 逐词包含）
        if ql == title_l:
            s += 60
        elif any(t in title_l for t in terms):
            s += 60
        # alias
        for al in aliases_l:
            if ql == al:
                s += 50
            elif any(t in al for t in terms):
                s += 40
        # tag（短词精确优先）
        for t in tags_l:
            if ql == t:
                s += 40
            elif any(term in t for term in terms):
                s += 40
        # summary
        if any(t in sum_l for t in terms):
            s += 20
        # 静态分类惩罚（trivial 少注入），非热度/新鲜度
        if "trivial" in tags_l:
            s -= 15
        return s

    # ---- 读取正文（冷存储按需取）------------------------------------------
    def read(self, id, package_id=None):
        """读取事件包正文（db-first 定位 filepath，支持跨包按 id 取）。

        id 入参兼容两种：文件名 stem（如 "veronica-base"）或完整 filepath。
        package_id=None（默认）→ 用当前句柄作用域；传 "" → 全局取首个匹配；
        传具体包 id 则限定。索引缺失/路径失效时回退到当前包 events_dir 直读。
        """
        c = self._conn()
        pid = package_id if package_id is not None else self.package_id
        row = None
        if id.endswith(".md"):
            # 直接按完整 filepath 取
            row = c.execute(
                "SELECT filepath FROM events WHERE filepath=?",
                (id,)).fetchone()
        elif pid:
            row = c.execute(
                "SELECT filepath FROM events "
                "WHERE package_id=? AND REPLACE(filepath, '\\', '/') LIKE ?",
                (pid, "%/" + id + ".md")).fetchone()
        else:
            row = c.execute(
                "SELECT filepath FROM events WHERE REPLACE(filepath, '\\', '/') LIKE ? LIMIT 1",
                ("%/" + id + ".md",)).fetchone()
        path = row[0] if (row and row[0]) else None
        if not path or not os.path.exists(path):
            path = os.path.join(self.events_dir, f"{id}.md")
            if not os.path.exists(path):
                return None
        with open(path, "r", encoding="utf-8") as f:
            pkg = EventPackage.from_markdown(f.read(), path)
        pkg.path = path          # 回填来源路径，供 link() 写回原目录
        return pkg

    def read_body(self, id):
        pkg = self.read(id)
        return pkg.body if pkg else None

    def read_section(self, id, heading):
        """按需读取正文里某个 ### / ## 小标题下的段落（锚点召回）。"""
        pkg = self.read(id)
        if not pkg:
            return None
        lines = pkg.body.splitlines()
        start, level = None, None
        for i, ln in enumerate(lines):
            m = re.match(r"^(#{2,6})\s+(.*)$", ln)
            if m and heading in m.group(2):
                start, level = i, len(m.group(1))
                break
        if start is None:
            return None
        out = [lines[start]]
        for j in range(start + 1, len(lines)):
            m = re.match(r"^(#{2,6})\s+", lines[j])
            if m and len(m.group(1)) <= level:
                break
            out.append(lines[j])
        return "\n".join(out).strip()

    def _anchor_body(self, rid, anchor):
        """取锚点章节正文：优先内联 body，缺失时从磁盘按 Chapter 回源。

        SCHEMA 规定 anchors 不内联 body（body 为唯一内容源），故召回需要章节
        正文时走 read_section 同款「按标题切章」逻辑回源。整文件 body 按 rid
        缓存，避免全库检索时逐锚点重复磁盘 I/O（同文件只直读一次）。
        rid 兼容完整 filepath 或文件名 stem（交给 self.read 解析）。
        """
        if not isinstance(anchor, dict):
            return ""
        inline = anchor.get("body")
        if inline:
            return inline
        chapter = anchor.get("Chapter") or anchor.get("title")
        if not chapter or not rid:
            return ""
        cache = getattr(self, "_body_cache", None)
        if cache is None:
            cache = self._body_cache = {}
        if rid not in cache:
            try:
                pkg = self.read(rid)
                cache[rid] = (pkg.body if pkg else "") or ""
            except Exception:
                cache[rid] = ""
        body = cache[rid]
        if not body:
            return ""
        # 切片结果按 (rid, chapter) 缓存：同文件多次取同一章（_score 与 _apply_field_weights
        # 各取一次）不重复 splitlines + 扫描，进一步压低大库检索的 Python 侧开销。
        scache = getattr(self, "_body_slice_cache", None)
        if scache is None:
            scache = self._body_slice_cache = {}
        skey = (rid, chapter)
        if skey in scache:
            return scache[skey]
        lines = body.splitlines()
        start, level = None, None
        for i, ln in enumerate(lines):
            m = re.match(r"^(#{2,6})\s+(.*)$", ln)
            if m and chapter in m.group(2):
                start, level = i, len(m.group(1))
                break
        if start is None:
            scache[skey] = ""
            return ""
        out = [lines[start]]
        for j in range(start + 1, len(lines)):
            m = re.match(r"^(#{2,6})\s+", lines[j])
            if m and len(m.group(1)) <= level:
                break
            out.append(lines[j])
        result = "\n".join(out).strip()
        scache[skey] = result
        return result

    # ---- 重建（索引损坏 = 重新扫描，不丢数据）-----------------------------
    def rebuild(self):
        """扫包目录下的事件 .md 的 front-matter，全量重建【当前包】索引。

        只删当前 package_id 的索引行（DELETE ... WHERE package_id=?），
        不清整库——其余包的索引行不受任何影响。这正是不再「每包一 db」
        后仍能安全装卸单个记忆文件夹的底气：rebuild 永远只动自己那一份。
        """
        self._init_db()   # 保证表存在（即便 db 被外部删除后重开）
        c = self._conn()
        c.execute("DELETE FROM events WHERE package_id=?", (self.package_id,))
        count = 0
        if os.path.isdir(self.root):
            for fn in os.listdir(self.root):
                if not fn.endswith(".md"):
                    continue
                if fn.endswith(".tmp"):
                    continue
                path = os.path.join(self.root, fn)
                if not os.path.isfile(path):
                    continue
                pkg = _load_for_index(path)
                if pkg is None or not pkg.id:
                    continue
                self._upsert(pkg, path)
                count += 1
        return count

    def rebuild_all(self, progress=None):
        """遍历仓库根下所有包目录，全量重建统一索引（清库后逐包重建）。

        一个自动化脚本即可整体刷新：
            python -m hma.engine rebuild-all --root memory

        progress：可选回调 progress(stage, message)，用于 GUI 逐包回报进度
        （stage ∈ {scan, pkg, done}）。默认 None = 静默（兼容旧调用）。
        """
        self._init_db()
        c = self._conn()
        count = 0
        repo = self.repo
        # 整库重建包成单个事务：1000 次 upsert 合并为 1 次提交，
        # 避免 autocommit（isolation_level=None）下每 INSERT 一次 fsync 的开销。
        # 事务内持有写锁，MCP 并发读会短暂阻塞——rebuild 是维护操作可接受；
        # 且原子提交保证"要么全建好、要么回到重建前"，比逐条提交更安全。
        if c.in_transaction:
            c.execute("ROLLBACK")
        c.execute("BEGIN IMMEDIATE")
        try:
            c.execute("DELETE FROM events")   # 清库，再逐包重建（同事务内）
            if progress:
                progress("scan", "开始全量重建索引（清除旧索引后逐包重扫）…")
            for dirpath, dirnames, filenames in os.walk(repo):
                # 跳过派生缓存：根级 目录结构树.md 自带 id front-matter，
                # 若纳入会被误索成 package_id='' 的游离根行
                if "目录结构树.md" in filenames:
                    filenames.remove("目录结构树.md")
                # R50：一个"包"= 直接含可解析事件 .md 的目录
                # （不再要求 events/ 子目录；命名空间目录自身不含 .md → 不会误判）
                md_events = []
                for fn in filenames:
                    if not fn.endswith(".md") or fn.endswith(".tmp"):
                        continue
                    _p = os.path.join(dirpath, fn)
                    if not os.path.isfile(_p):
                        continue
                    # 脚本派生视图由 _load_for_index 内部判标记跳过；这里仅收集候选路径
                    md_events.append(_p)
                if not md_events:
                    continue
                pkg_dir = dirpath
                pid = _pkg_id(pkg_dir, repo)
                if progress:
                    progress("pkg", "%s  (%d 事件)" % (pid or "(仓库根)", len(md_events)))
                for _p in md_events:
                    pkg = _load_for_index(_p)
                    if pkg is None or not pkg.id:
                        continue
                    self._upsert(pkg, _p, package_id=pid)
                    count += 1
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        if progress:
            progress("done", "共重建 %d 条事件索引" % count)
        return count

    # ---- 装卸（一个脚本直接装/卸某个记忆文件夹）-------------------------
    def install(self, pkg_dir, rm=False):
        """把一个记忆文件夹（直接含事件 .md）装入统一索引。

        等价于：以该包目录推导仓库根、清掉该 package_id 旧行、扫事件 .md 重插。
        只动目标包自己的索引行，其余包不受影响。
        可选 rm=True：装完后删除【源】文件夹（谨慎！已装内容已在统一索引）。
        """
        pkg_dir = os.path.abspath(pkg_dir)
        # R50：合法包 = 直接含事件 .md（不再要求 events/ 子目录）
        mds = [fn for fn in os.listdir(pkg_dir)
                if fn.endswith(".md") and not fn.endswith(".tmp")
                and os.path.isfile(os.path.join(pkg_dir, fn))] \
            if os.path.isdir(pkg_dir) else []
        if not mds:
            raise ValueError(f"不是合法记忆包（缺事件 .md）：{pkg_dir}")
        pid = _pkg_id(pkg_dir, self.repo)
        c = self._conn()
        c.execute("DELETE FROM events WHERE package_id=?", (pid,))
        count = 0
        for fn in sorted(mds):
            path = os.path.join(pkg_dir, fn)
            pkg = _load_for_index(path)
            if pkg is None or not pkg.id:
                continue
            self._upsert(pkg, path, package_id=pid)
            count += 1
        if rm:
            shutil.rmtree(pkg_dir, ignore_errors=True)
        return count

    def uninstall(self, package_id, rm=False):
        """从统一索引卸下某个记忆文件夹（按 package_id 删索引行）。

        可选 rm=True：同时删除磁盘上的包文件夹（<repo>/<package_id>）。
        package_id 为空时拒绝（避免误删仓库根）。
        """
        if not package_id:
            raise ValueError("package_id 为空：拒绝卸载仓库根")
        c = self._conn()
        c.execute("DELETE FROM events WHERE package_id=?", (package_id,))
        if rm:
            target = os.path.join(self.repo, package_id)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
        return package_id

    # ---- 工具 -----------------------------------------------------------------
    def list_all(self):
        c = self._conn()
        if self.package_id:
            rows = c.execute(
                "SELECT filepath,title,tags,pkage_updated FROM events "
                "WHERE package_id=? ORDER BY pkage_updated DESC, filepath",
                (self.package_id,)).fetchall()
        else:
            rows = c.execute(
                "SELECT filepath,title,tags,pkage_updated FROM events "
                "ORDER BY pkage_updated DESC, filepath").fetchall()
        return [(os.path.splitext(os.path.basename(r[0]))[0], r[1] or "",
                 r[2] or "", r[3] or "") for r in rows]

    def orchestrate(self, sub_queries, top_k=5, keywords=None, scope=None,
                    allow_abstain=True):
        """multi 模式扇出-合并：AI 已拆好 sub_queries 清单，引擎确定性循环 query_anchors
        各子问并按子问分组返回。不内置拆问（拆问归 AI 理解层，CEMA）。

        返回 [(sub_q, hits, reason_or_None), ...]，hits 为
        [(pkg_id, anchor_title, anchor_about, locator, score), ...]；
        reason 非空表示该子问被拒答（allow_abstain 触发）。跨子问按 (pkg_id, anchor_title)
        去重，避免多子问命中同锚点重复罗列。
        """
        out = []
        seen = set()
        for sq in (sub_queries or []):
            sq = str(sq).strip()
            if not sq:
                continue
            hits = self.query_anchors(
                sq, top_k=top_k, package_id=None, dedup_packages=False,
                use_field_weights=True, allow_abstain=allow_abstain,
                keywords=keywords, scope=scope)
            if isinstance(hits, dict):           # allow_abstain=True 结构化返回
                if hits.get("abstain"):
                    out.append((sq, [], hits.get("reason")))
                    continue
                hits = hits["answer"]
            deduped = []
            for (pkg_id, a_title, a_summary, locator, score) in hits:
                key = (pkg_id, a_title)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append((pkg_id, a_title, a_summary, locator, score))
            out.append((sq, deduped, None))
        return out

    def list_all_in_scope(self, scope=None, top_k=None):
        """枚举模式（QueryEnvelope mode=enumerate）的专用返回形态：列出 scope 子树内的
        全部包（确定性 filepath 排序，非 Top-K 相关度），供「该范围内都有什么」类枚举问。
        零-ML；scope=None 退化为全仓 list。"""
        c = self._conn()
        scl, spar = _scope_clause(scope, self.root)
        sql = "SELECT filepath,title,summary FROM events"
        params = []
        if scl:
            sql += " WHERE " + scl
            params += spar
        sql += " ORDER BY filepath"
        if top_k:
            sql += " LIMIT ?"
            params.append(int(top_k))
        rows = c.execute(sql, params).fetchall()
        out = []
        for fp, title, summary in rows:
            rid = fp
            if self.root and rid.startswith(self.root):
                rid = rid[len(self.root):]
            rid = rid.strip("/\\").removesuffix(".md")
            out.append((rid, title or "", summary or ""))
        return out

    def list_summaries(self):
        """(id, title, summary) 列表，仅供关联发现等内部用途，仅扫索引。
        当前包作用域（repo 级句柄 package_id="" 则全局）。"""
        c = self._conn()
        if self.package_id:
            rows = c.execute(
                "SELECT filepath,title,summary FROM events "
                "WHERE package_id=? ORDER BY pkage_updated DESC, filepath",
                (self.package_id,)).fetchall()
        else:
            rows = c.execute(
                "SELECT filepath,title,summary FROM events "
                "ORDER BY pkage_updated DESC, filepath").fetchall()
        return [(os.path.splitext(os.path.basename(r[0]))[0], r[1] or "",
                 r[2] or "") for r in rows]


# ---------------------------------------------------------------------------
# 锚点派生（确定性、OC 无关，纯 stdlib；供 EXE 打包安全复用）
# ---------------------------------------------------------------------------
# 标题行：`#`~`######`，捕获层级与标题文本（兼容行尾 `#` 闭包）
_anchor_heading_re = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")

# 句末切分（中英文句号/问叹/分号）
_anchor_sent_split = re.compile(r"(?<=[。！？!?；;\.])\s*")

# 表格分隔行（如 `| --- | --- |`）
_anchor_table_sep = re.compile(r"^[\s|:\-|]+$")




def _anchor_first_sentence(text):
    """取正文首句（跳过空行/表格行/标题行，到第一个句末标点）。"""
    text = (text or "").strip()
    if not text:
        return ""
    for raw in re.split(r"\n+", text):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("|") or _anchor_table_sep.match(line):
            continue  # 表格/分隔行不参与摘要
        parts = _anchor_sent_split.split(line)
        if parts and parts[0].strip():
            return parts[0].strip()
    return ""


def derive_anchors(md_text, max_level=6):
    """从 Markdown 正文派生章级锚点列表。

    返回 [{Chapter, about, keywords}, ...]（v2 锚点 schema：无 locator/tags/body；
    body 为唯一内容源，anchors 仅关键词/梗概、不内联 body，召回时按需 read_section 回源）。
    默认 max_level=6：取 `##`~`######` 全层级（写入侧细切，读取侧成本最小化；
    章节层级过细导致内容被切断属原文文档本身结构问题，非检索侧责任）。
    """
    lines = (md_text or "").splitlines()
    heads = []
    for i, ln in enumerate(lines):
        m = _anchor_heading_re.match(ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))

    anchors = []
    for k, (i, lvl, title) in enumerate(heads):
        if not (2 <= lvl <= max_level):
            continue
        body_start = i + 1
        body_end = len(lines)
        for j in range(k + 1, len(heads)):
            if heads[j][1] <= lvl:
                body_end = heads[j][0]
                break
        body = "\n".join(lines[body_start:body_end])
        anchors.append({
            "Chapter": title,
            "about": _anchor_first_sentence(body),
            "keywords": [],
        })
    return anchors


def _anchor_all_heading_texts(md_text):
    """收集正文所有层级标题文本（任意 #~######），用于区分
    '用户手写锚定的子节(### 等)' 与 '已删除的 stale 锚点'。"""
    out = []
    for ln in (md_text or "").splitlines():
        m = _anchor_heading_re.match(ln)
        if m:
            out.append(m.group(2).strip())
    return out


def merge_anchors(existing, body, max_level=6):
    """把'自动派生(打底)' 与 '用户手写(覆盖)' 合并为最终锚点列表。

    以 Chapter(=标题原文，兼容旧 locator/title) 为键，规则：
      - 正文有个新 ##（existing 无对应）→ 补派生版（自动打底）
      - 已有 ## 且 existing 与派生一致(about+keywords 同) → 原地刷新派生版
      - 已有 ## 但 existing 被手改(about 或 keywords 不同) → 留用户的版本
      - 正文删了某 ##（原 anchor 失效）→ 删
      - 用户手写锚定到非 ## 的子节(### 等，派生不覆盖) → 留
    返回新列表；不修改入参。纯 stdlib、无外部依赖（供 EXE 打包安全）。
    """
    existing = existing or []
    derived = derive_anchors(body, max_level=max_level)
    _derived_by_ch = {a["Chapter"]: a for a in derived}
    all_headings = set(_anchor_all_heading_texts(body))

    def _key(a):
        return a.get("Chapter") or a.get("title") or a.get("locator")

    result = []
    seen = set()
    for d in derived:
        loc = d["Chapter"]
        seen.add(loc)
        e = None
        for x in existing:
            if _key(x) == loc:
                e = x
                break
        if e is None:
            result.append(d)                                  # 新 ## → 打底
        elif e.get("about") == d["about"] and e.get("keywords") == d["keywords"]:
            result.append(d)                                  # 仍=派生 → 刷新(无害)
        else:
            result.append({k: v for k, v in e.items() if k != "body"})  # 手改 → 留用户版(去 body)
    for e in existing:
        loc = _key(e)
        if loc in seen:
            continue                                          # 上面已处理
        if loc in all_headings:
            result.append({k: v for k, v in e.items() if k != "body"})  # 用户锚定子节(###等) → 留(去 body)
        # else: 真 stale（## 被删）→ 丢弃
    return result


if __name__ == "__main__":
    import tempfile
    d = tempfile.mkdtemp()
    m = Memory(os.path.join(d, ".memory"))
    m.write("proj-x", "X 项目", "架构决策", ["x架构"], ["project", "decision"],
            body="# X\n初始综述")
    print("query 'x架构':", m.query("x架构"))
    print("rebuild ->", m.rebuild())
    print("query after rebuild:", m.query("架构"))
