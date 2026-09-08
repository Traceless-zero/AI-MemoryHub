# -*- coding: utf-8 -*-
"""aggregate_time —— Type 8 计数聚合 + Type 6 时间硬过滤 + 自然语言时间意图（S3 拆分）。

三块职责（与 hma/time_iso.py 分工：time_iso 只管【相对时间→绝对 ISO 换算】，
本模块 parse_time_hint 只管【从问句抽取时间意图 TimeHint】，db_aggregate /
time_filter 是 index.db 上的确定性只读查询）：
  TimeHint / parse_time_hint   —— 问句时间意图抽取（供检索软加权与硬过滤共用）
  _agg_build_where / db_aggregate —— 结构化计数（只读 URI + 列/算子双白名单）
  time_filter / _time_hard_match  —— 月份级硬过滤（不匹配月即剔除）
Memory.aggregate / Memory.filter_by_time 是 hma_core 上的薄转发，MCP 层经其调用。
_scope_clause 定义在 hma_core（检索侧共享），此处运行时延迟解析避免循环 import。
"""

import json
import json
import os
import re
import sqlite3
from datetime import date, timedelta


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
# 年份：允许后面紧跟 CJK 字符（如「2026年」）。原 \b(19|20)\d{2}\b 的尾边界
# 在「2026年」上失效——Python 把 CJK 视为 \w，6 与 年 之间无词边界 → 整年解析落空，
# 导致「2026年」类裸年中文时间意图完全解析不到年份（时间硬过滤/软加权双双失能）。
# 改为首边界 (?<![\w])（非词字符前导，避免匹配 12026 内部）+ 尾边界 (?![\d])（仅禁数字续接，
# 放行 年 等 CJK）——只扩匹配、不削任何既有匹配。
_RE_YEAR = re.compile(r"(?<![\w])(?:19|20)\d{2}(?![\d])")
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

    # 中文相对时间预解析（委托 time_iso 模块：前天/上周三/最近三天…确定性封闭集）。
    # 命中 → days/windows 注入（与英文级联叠加）；未命中 → 落回既有级联（零回归）。
    # fail-open：预解析任何异常不阻断检索。
    try:
        from ..time_iso import parse_text as _ti_parse
        for _r in _ti_parse(t, today=now):
            _y1, _m1, _d1 = (int(x) for x in _r["start"].split("-"))
            days.add(date(_y1, _m1, _d1))
            years.add(_y1)
            _y2, _m2, _d2 = (int(x) for x in _r["end"].split("-"))
            if (_y1, _m1, _d1) != (_y2, _m2, _d2):
                windows.append((date(_y1, _m1, _d1), date(_y2, _m2, _d2)))
    except Exception:
        pass  # 预解析 fail-open

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



def _scope_clause_late(scope, root):
    """运行时解析 hma_core._scope_clause（S3 拆分后其仍居 hma_core——检索侧三处共用；
    延迟解析避免循环 import）。"""
    from .. import hma_core
    return hma_core._scope_clause(scope, root)


_AGG_COL_WHITELIST = {
    "package_id", "filepath", "title", "summary", "tags", "linked",
    "pkage_created", "pkage_updated", "anchors", "person", "event_date",
    "location", "topic",
}
_AGG_UNITS = {"packages", "events", "persons", "locations", "topics"}

def _agg_build_where(scope, root, filters):
    """返回 (frags, params)。frags 是拼到 WHERE 后的 SQL 片段列表。

    列名经白名单校验、算子限 =/like、值一律 ? 参数化——三重护栏保证无注入。"""
    frags, params = [], []
    scl, spar = _scope_clause_late(scope, root)
    if scl:
        frags.append(scl)
        params += spar
    for col, spec in (filters or {}).items():
        if col not in _AGG_COL_WHITELIST:
            raise ValueError(f"db_aggregate: 列 {col!r} 不在白名单，已拒绝")
        if isinstance(spec, tuple) and len(spec) == 2:
            op, val = spec
        else:
            op, val = "=", spec
        if op not in ("=", "like"):
            raise ValueError(f"db_aggregate: 算子 {op!r} 不在白名单(=/like)")
        frags.append(f"events.{col} {op} ?")   # 列名白名单、值参数化
        params.append(val)
    return frags, params


def db_aggregate(db_path, unit, filters=None, scope=None, return_list=False,
                 top_k=500, root=None):
    """Type 8 计数：在 index.db 上做确定性结构化 COUNT / 枚举。

    unit:
      packages  -> 去重 package_id 计数（包文件夹数）
      events    -> 各包 anchors 子事件总数（解析 JSON，Python 侧求和）
      persons   -> person 列 json_each 去重规范名计数
      locations -> location 列 json_each 去重规范名计数
      topics    -> topic 列 json_each 去重规范名计数
    return_list=False -> 返回 int（计数）；True -> 返回 list[str]（枚举实体）。
    top_k 仅 return_list 生效，硬上限 500（护栏 6）。"""
    if unit not in _AGG_UNITS:
        raise ValueError(f"db_aggregate: unit 必须是 {sorted(_AGG_UNITS)} 之一")
    if root is None:
        root = os.path.dirname(os.path.abspath(db_path))
    top_k = min(int(top_k), 500)               # 护栏 6：硬上限

    cx = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)  # 护栏 5：只读
    try:
        c = cx.cursor()
        frags, params = _agg_build_where(scope, root, filters)
        where = (" WHERE " + " AND ".join(frags)) if frags else ""

        if unit == "packages":
            if return_list:
                sql = f"SELECT DISTINCT package_id FROM events{where} LIMIT {top_k}"
                return [r[0] for r in c.execute(sql, params).fetchall()]
            sql = f"SELECT COUNT(DISTINCT package_id) FROM events{where}"
            return c.execute(sql, params).fetchone()[0]

        if unit in ("persons", "locations", "topics"):
            col = {"persons": "person", "locations": "location",
                   "topics": "topic"}[unit]
            # 护栏 4：实体列走 json_each 取 key；json_valid 防脏数据报错
            join = f"events, json_each(events.{col})"
            nonempty = (f"events.{col} IS NOT NULL AND events.{col} <> '' "
                        f"AND json_valid(events.{col})=1")
            where2 = (" WHERE " + nonempty +
                      (" AND " + " AND ".join(frags) if frags else ""))
            if return_list:
                sql = f"SELECT DISTINCT key FROM {join}{where2} LIMIT {top_k}"
                return [r[0] for r in c.execute(sql, params).fetchall()]
            sql = f"SELECT COUNT(DISTINCT key) FROM {join}{where2}"
            return c.execute(sql, params).fetchone()[0]

        if unit == "events":
            # anchors 是 JSON 数组，每条=子事件；逐行解析求和（确定性）
            sql = f"SELECT package_id, anchors FROM events{where}"
            rows = c.execute(sql, params).fetchall()
            if return_list:
                out = []
                for pkg_id, anc in rows:
                    try:
                        arr = json.loads(anc) if anc else []
                    except Exception:
                        arr = []
                    for a in arr:
                        if isinstance(a, dict) and a.get("Chapter"):
                            out.append(f"{pkg_id} :: {a['Chapter']}")
                            if len(out) >= top_k:
                                return out
                return out
            total = 0
            for (_pkg_id, anc) in rows:
                try:
                    arr = json.loads(anc) if anc else []
                except Exception:
                    arr = []
                total += sum(1 for a in arr if isinstance(a, dict))
            return total
    finally:
        cx.close()


def time_filter(db_path, time_hint, scope=None, root=None, top_k=500):
    """Type 6（硬时间过滤）：解析自然语言时间意图，硬留 event_date 命中月份（含年）的包。

    复用生产 parse_time_hint 抽时间意图（TimeHint），对每包 event_date 做确定性
    月份匹配——这是「硬过滤」，不匹配月即剔除（与软加权 _apply_field_weights
    只偏不强制相对）。零 ML、只读连接。返回匹配包 package_id 列表（cap 500）。
    无时间意图（time_hint 解析为空）→ 返回 []（调用方只在检测到时间意图时调用）。
    """
    th = parse_time_hint(time_hint)
    if not th:
        return []
    if root is None:
        root = os.path.dirname(os.path.abspath(db_path))
    top_k = min(int(top_k), 500)
    cx = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)  # 只读
    try:
        c = cx.cursor()
        scl, spar = _scope_clause_late(scope, root)
        sql = "SELECT DISTINCT package_id, event_date, filepath FROM events"
        params = []
        if scl:
            sql += " WHERE " + scl
            params += spar
        rows = c.execute(sql, params).fetchall()
        out, seen = [], set()
        for pkg_id, edate, _fp in rows:
            if pkg_id in seen:          # 同包多子事件（不同 filepath）→ 按包去重
                continue
            if _time_hard_match(th, edate):
                seen.add(pkg_id)
                out.append(pkg_id)
                if len(out) >= top_k:
                    break
        return out
    finally:
        cx.close()


def _time_hard_match(th, edate):
    """硬过滤判定：edate 是否命中时间意图的「月（含年）」级。

    比 TimeHint.match 更严：当年月对(ym)非空时要求包 (年,月) 确在 ym 内，
    避免「2026年3月」把「2024年3月」也留下（month-agnostic-of-year 仅在没有
    年意图、只有月份词时启用）。年范围事件日期（'1792-1822'）无月份信号，
    命中不了具体月 → 被剔除（与软加权只偏不强制的语义一致）。
    """
    if not edate or edate == "—":
        return False
    m = _RE_ISO.search(edate)
    if not m:
        return False
    y, mo = int(m.group(1)), int(m.group(2))
    d = int(m.group(3)) if m.group(3) else None
    if d:
        day = None
        try:
            day = date(y, mo, d)
        except ValueError:
            day = None
        if day and day in th.days:
            return True
        for lo, hi in th.windows:
            if day and lo <= day <= hi:
                return True
    if (y, mo) in th.ym:
        return True
    if th.ym and y in {yy for (yy, _) in th.ym} and mo in th.months:
        return True
    if not th.ym and mo in th.months:
        return True
    if not th.fine and y in th.years:
        return True
    return False




