# -*- coding: utf-8 -*-
"""time_iso —— 中文相对时间的层级确定性解析（零依赖、零 ML）。

架构（2026-09-06 v2 定稿）：**层级性二级解析**
  一级 · 粒度定位：日级（前天/昨天/明天/后天…）→ 周级（上周/本周/下周）→
          月级（上个月/本月/下个月）→ 年级（去年/今年/明年/前年）
  二级 · 粒度内细化：周级 + 周三 → 该周的周三；月级 + 15号/月底 → 该月的 15 日/末日；
          日级 + 凌晨/晚上 → 该日的时段窗口（tod 字段）
  边界 · 之前/以来：X之前（不含当日）/ X以来（含当日起）——开放边界语义

词表是有限封闭集：给定锚点日期，全部映射唯一确定——「结构性可脚本化」的对象；
开放集转述（换措辞/那阵子/早些时候）仍归理解层，二者划清界限。
不存在的日期（「2月30号」）→ 未识别，不静默修正。

接入点：`hma_core.parse_time_hint` 顶部委托本模块（命中 → days/windows 注入 TimeHint，
与英文级联叠加）；daylog 时间描述唤起（read_day 前置归一）。
"""

import datetime as dt
import re

ISO = "%Y-%m-%d"

# ============================== 一级 · 粒度词表 ==============================
DAY_G = {"大前天": -3, "前天": -2, "昨天": -1, "昨日": -1, "今天": 0,
         "今日": 0, "明天": 1, "明日": 1, "后天": 2, "大后天": 3}
WEEK_G = {"上周": -1, "本周": 0, "这周": 0, "下周": 1}
MONTH_G = {"上个月": -1, "上月": -1, "本月": 0, "这个月": 0, "下个月": 1, "下月": 1}
YEAR_G = {"前年": -2, "去年": -1, "今年": 0, "明年": 1}

_G_WORDS = sorted(list(DAY_G) + list(WEEK_G) + list(MONTH_G) + list(YEAR_G),
                  key=len, reverse=True)
_G_RE = re.compile("(" + "|".join(_G_WORDS) + ")(.*)")

# ============================== 小时级 · 时段边界表 ==============================
# 约定值可调；按 24h 阶梯互不重叠；22 点后归深夜
TOD_TABLE = {
    "凌晨": ("00:00", "05:59"),
    "半夜": ("00:00", "05:59"),   # 归凌晨
    "早上": ("06:00", "08:59"),
    "早晨": ("06:00", "08:59"),   # = 早上
    "上午": ("09:00", "11:59"),
    "中午": ("12:00", "13:59"),
    "下午": ("14:00", "17:59"),
    "傍晚": ("18:00", "18:59"),
    "晚上": ("19:00", "21:59"),
    "深夜": ("22:00", "23:59"),
}

# 中文数词 / 星期
_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
WEEKDAY_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
_BOUNDARY_RE = re.compile(r"(之前|以前|以来|之后|以后|以内)\s*$")


def _iso(d):
    return d.strftime(ISO)


def _cn_to_int(s):
    """中文数词 → 整数（一~十及组合；阿拉伯数字直接转）；失败 None。"""
    if s.isdigit():
        return int(s)
    total, pending = 0, 0
    for ch in s:
        v = _CN_NUM.get(ch)
        if v is None:
            return None
        if ch == "十":
            total += (pending or 1) * 10
            pending = 0
        else:
            pending = v
    return total + pending


def _month_span(today, k):
    """相对月 k（-1 上个月 / 0 本月 / 1 下个月）的 [首日, 末日]。"""
    first_this = today.replace(day=1)
    if k == 0:
        lo = first_this
    elif k == -1:
        lo = (first_this - dt.timedelta(days=1)).replace(day=1)
    else:
        y, m0 = divmod(first_this.month - 1 + k, 12)
        lo = first_this.replace(year=first_this.year + y, month=m0 + 1)
    nxt = (lo.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    hi = nxt - dt.timedelta(days=1)
    return lo, hi


def _week_span(today, k):
    """相对周 k（-1 上周 / 0 本周 / 1 下周）的 [周一, 周日]（周一为一周起点）。"""
    mon = today - dt.timedelta(days=today.weekday())
    base = mon + dt.timedelta(weeks=k)
    return base, base + dt.timedelta(days=6)


# ============================== 二级 · 粒度内细化 ==============================
def _within_week(span_lo, rest, today):
    """周级细化：周X/礼拜X（或裸星期字）→ 区间内的那个星期几。"""
    m = re.fullmatch(r"(?:礼拜|周)?([一二三四五六日天])", rest)
    if not m:
        return None
    wd = WEEKDAY_CN[m.group(1)]
    d = span_lo + dt.timedelta(days=wd - 1)
    return {"kind": "day", "start": _iso(d), "end": _iso(d)}


def _within_month(span_lo, span_hi, rest, today):
    """月级细化：X号/X日（月内日）、月初/月中/月底。"""
    if rest == "月初":
        d = span_lo
    elif rest == "月底":
        d = span_hi
    elif rest == "月中":
        d = span_lo + (span_hi - span_lo) // 2
    else:
        m = re.fullmatch(r"([0-9一二两三四五六七八九十]{1,3})\s*[号日]", rest)
        if not m:
            return None
        n = _cn_to_int(m.group(1))
        if n is None or not (1 <= n <= (span_hi - span_lo).days + 1):
            return None  # 该月不存在的日期 → 未识别，不静默修正
        d = span_lo + dt.timedelta(days=n - 1)
    return {"kind": "day", "start": _iso(d), "end": _iso(d)}


# ============================== 解析主流程 ==============================
def parse(expr, today=None, _depth=0):
    """两级解析 + 边界词。返回 {"kind","start","end"[,"tod"|"boundary"]}；失败 None。

    today 为锚点（date 或 None=真实今天）。
    """
    if today is None:
        today = dt.date.today()
    e = expr.strip().strip("的了这那 　")
    if not e or _depth > 1:
        return None

    # ⓪ 边界词（后缀）：X之前/以前 = 不含当日；X以来/之后/以后 = 含当日起
    m = _BOUNDARY_RE.search(e)
    if m and _depth == 0:
        core = parse(e[:m.start()], today, _depth=_depth + 1)
        if core:
            bw = m.group(1)
            if bw in ("之前", "以前"):
                return {"kind": "before", "boundary": core["start"]}
            return {"kind": "after", "boundary": core["start"]}

    # ISO 绝对日期直通
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", e):
        y, m, d = (int(x) for x in e.split("-"))
        try:
            day = dt.date(y, m, d)
        except ValueError:
            return None
        return {"kind": "day", "start": _iso(day), "end": _iso(day)}

    # 半个月 前/后（半月 = 15 天）
    m = re.fullmatch(r"半个?月?(前|后)", e)
    if m:
        d = today + dt.timedelta(days=(-15 if m.group(1) == "前" else 15))
        return {"kind": "day", "start": _iso(d), "end": _iso(d)}

    # N 天 前/后（中文数词或阿拉伯）
    m = re.fullmatch(r"([0-9一二两三四五六七八九十]+)\s*天\s*(前|后)", e)
    if m:
        n = _cn_to_int(m.group(1))
        if n is None:
            return None
        d = today + dt.timedelta(days=(-n if m.group(2) == "前" else n))
        return {"kind": "day", "start": _iso(d), "end": _iso(d)}

    # 最近 / 近 N 天·周·个月（记忆召回第一高频问法；区间止于今天）
    m = re.fullmatch(r"(最近|近|这)([0-9一二两三四五六七八九十]+)?个?(天|周|星期|个月|月)", e)
    if m:
        unit = m.group(3)
        n = _cn_to_int(m.group(2)) if m.group(2) else None
        if unit in ("周", "星期"):
            n = (n or 1) * 7
            lo = today - dt.timedelta(days=n - 1)
            return {"kind": "range", "start": _iso(lo), "end": _iso(today)}
        if unit in ("个月", "月"):
            n = n or 1
            lo, hi = _month_span(today, 0)
            y, m0 = divmod(lo.month - 1 - (n - 1), 12)
            lo = lo.replace(year=lo.year + y, month=m0 + 1, day=1)
            return {"kind": "range", "start": _iso(lo), "end": _iso(today)}
        n = (n or 3) if m.group(2) is None else (n or 1)
        lo = today - dt.timedelta(days=n - 1)
        return {"kind": "range", "start": _iso(lo), "end": _iso(today)}

    # ① 一级粒度定位（长词优先）+ ② 二级粒度内细化
    m = _G_RE.fullmatch(e)
    if m:
        g, rest = m.group(1), m.group(2).strip()
        if g in DAY_G:
            d = today + dt.timedelta(days=DAY_G[g])
            r = {"kind": "day", "start": _iso(d), "end": _iso(d)}
            if rest in TOD_TABLE:
                r["tod"] = {"name": rest, "from": TOD_TABLE[rest][0], "to": TOD_TABLE[rest][1]}
            return r
        if g in WEEK_G:
            lo, hi = _week_span(today, WEEK_G[g])
            if rest:
                r2 = _within_week(lo, rest, today)
                if r2:
                    return r2
            return {"kind": "range", "start": _iso(lo), "end": _iso(hi)}
        if g in MONTH_G:
            lo, hi = _month_span(today, MONTH_G[g])
            if rest:
                r2 = _within_month(lo, hi, rest, today)
                if r2:
                    return r2
            return {"kind": "range", "start": _iso(lo), "end": _iso(hi)}
        if g in YEAR_G:
            y = today.year + YEAR_G[g]
            mm = None
            if rest:
                mm = _cn_to_int(re.fullmatch(r"([0-9一二三四五六七八九十]+)月份?", rest).group(1)) \
                    if re.fullmatch(r"[0-9一二三四五六七八九十]+月份?", rest) else None
            if mm:
                lo = dt.date(y, mm, 1)
                hi = (lo.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
                return {"kind": "range", "start": _iso(lo), "end": _iso(hi)}
            return {"kind": "range", "start": f"{y}-01-01", "end": f"{y}-12-31"}

    # ③ 裸细化词（无粒度前缀 → 默认本周/本月）：周三 / 礼拜五 / 月底
    m = re.fullmatch(r"(?:礼拜|周)([一二三四五六日天])", e)
    if m:
        lo, hi = _week_span(today, 0)
        return _within_week(lo, m.group(1), today)
    if e in ("月初", "月中", "月底"):
        lo, hi = _month_span(today, 0)
        return _within_month(lo, hi, e, today)

    # ④ 裸时段词（默认今天 + 时段窗口）
    if e in TOD_TABLE:
        return {"kind": "day", "start": _iso(today), "end": _iso(today),
                "tod": {"name": e, "from": TOD_TABLE[e][0], "to": TOD_TABLE[e][1]}}

    return None


def parse_text(text, today=None):
    """从自由文本中按顺序抽取全部可识别的时间表达式（扫描模式）。"""
    out, seen = [], set()
    pat = re.compile(
        r"|(?:最近|近|这)(?:[0-9一二两三四五六七八九十]+|几)?个?(?:天|周|星期|个月|月)"
        r"|(?:大)?(?:前天|后天|昨天|昨日|今天|今日|明天|明日|大后天)"
        r"(?:凌晨|半夜|早上|早晨|上午|中午|下午|傍晚|晚上|深夜)?"
        r"|上周|本周|这周|下周|(?:上|这|本|下)个?月|去年|今年|明年|前年"
        r"|(?:上周|本周|这周|下周|这|本)?(?:礼拜|周)[一二三四五六日天]"
        r"|(?:上|这|本|下)个?月(?:初|中|底)|月初|月中|月底")
    for m in pat.finditer(text):
        expr = m.group(0)
        if expr in seen:
            continue
        r = parse(expr, today)
        if r:
            seen.add(expr)
            out.append({"expr": expr, **r})
    return out
