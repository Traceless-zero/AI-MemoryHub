# -*- coding: utf-8 -*-
"""daylog —— 单日记录包（时间轴索引层，叙事型）。

CEMA 主记忆库按「主题而非时间线」组织（设计文档 §4.4），夜间归档把话题
溶进主题事件包后，「那一天发生了什么」的时间线索随之丢失。本模块补上
这条正交的时间轴，且不违反 §4.4：

    单日记录包只存「一天的叙事 + 关联 ID 链接 + 关键词 tag」，
    是只读时间索引；权威叙事永远在主题事件包（活文档）里。

借鉴 WB 自带 memory 的收录结构 —— **叙事块 + 结构化侧车**：
    正文 = 这一天按时间顺序流动的叙事（像写日记，可回读的故事）；
    结构化字段（linked / tags / front-matter）只作机器索引侧车，不破坏可读性。

数据模型（复用现有 EventPackage 原语，零新 schema）：
    id      = daylog-YYYY-MM-DD（一天一包，id 内嵌日期 → 日期即键）
    body    = 一段连贯叙事：每个「进展」一个段落，段尾跟 `<!--beat ...-->`
              侧车注释（存该段的 linked / tags）；包末附一句索引 blockquote
    linked  = 当天所有进展链接到的主题包 id 并集（front-matter）
    tags    = 当天所有进展关键词并集（front-matter，并兼作锚点）
    anchors = 由 tags 构造（确定性，使单日包可被 query_anchors 发现）

无状态铁律（§13）合规性：
    时间只作 WHERE 过滤键（id 前缀字符串比较，确定性、可复现），
    结果按日历序排列（客观时间顺序，非热度/新鲜度相关性权重）。

两种唤起：
    全天模糊型「我那天都干了些什么」 → read_day / days_in_range 列全部叙事
    精准搜寻型「那天我是不是让你干了 XXX」 → filter_beats 在叙事段内
    做确定性关键词匹配（命中后经 linked 一对一映射调主题包正文，§2.3）
"""

import re
from datetime import date

from .hma_core import Memory

DAY_PREFIX = "daylog-"

# 段侧车注释：<!--beat linked:cema-design,hma tags:CEMA,HMA-->
_BEAT_RE = re.compile(r"<!--\s*beat\s*(.*?)\s*-->", re.S)
_META_KV = re.compile(r"(\w+)\s*:\s*([^<]*)")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def ensure_date(s):
    """校验并规范化 YYYY-MM-DD；非法则抛 ValueError。"""
    return date.fromisoformat(str(s).strip()).isoformat()


def day_id(date_str):
    return DAY_PREFIX + ensure_date(date_str)


def _split_csv(v):
    if not v:
        return []
    if isinstance(v, (list, tuple)):
        items = [str(x).strip() for x in v]
    else:
        items = [x.strip() for x in str(v).split(",")]
    return [x for x in items if x]


def _dedup(seq):
    out, seen = [], set()
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _clean_prose(s):
    """去标题行/索引行/空行，只留叙事正文。"""
    out = []
    for line in (s or "").splitlines():
        st = line.strip()
        if not st:
            continue
        if st.startswith("#") or st.startswith(">"):
            continue
        out.append(st)
    return "\n".join(out)


def _parse_beat_meta(s):
    linked, tags = [], []
    for k, v in _META_KV.findall(s or ""):
        if k == "linked":
            linked = _split_csv(v)
        elif k == "tags":
            tags = _split_csv(v)
    return {"linked": linked, "tags": tags}


def _index_blockquote(linked, tags):
    return ("> 索引 · linked: [%s] · tags: [%s]"
            % (", ".join(linked), ", ".join(tags)))


# ---------------------------------------------------------------------------
# 写入：追加一段叙事（收录即写）
# ---------------------------------------------------------------------------
def append_beat(root, text, linked=None, tags=None,
                date_str=None, trigger="daylog.append"):
    """向某天的单日记录包追加一段叙事。

    root      daylog 专用落库目录（如 memory/日志）
    text      一段叙事（必填）：描述这天发生的一件事 / 一个进展，
              像写日记，可用「先是 / 随后 / 最后 / 接着」等连接词让一天连贯。
    linked    该段链接到的主题事件包 id（列表或逗号分隔串）
    tags      该段关键词 tag（列表或逗号分隔串）
    date_str  归属日期 YYYY-MM-DD；缺省今天

    返回 (rid, n_beats)。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("叙事内容不能为空")
    d = ensure_date(date_str or date.today().isoformat())
    rid = day_id(d)
    linked = _split_csv(linked)
    tags = _split_csv(tags)
    meta = "linked:%s tags:%s" % (",".join(linked), ",".join(tags))
    beat_block = "%s\n<!--beat %s-->" % (text, meta)

    mem = Memory(root)
    try:
        pkg = mem.read(rid)
        if pkg:
            body = _strip_index(pkg.body)
            new_body = body.rstrip() + "\n\n" + beat_block
            all_linked = _dedup(pkg.linked + linked)
            all_tags = _dedup(pkg.tags + tags)
            created = pkg.created
        else:
            head = "# %s 单日记录" % d
            new_body = head + "\n\n" + beat_block
            all_linked, all_tags, created = linked, tags, d
        n = len(parse_beats(new_body))
        full_body = new_body.rstrip() + "\n\n" + _index_blockquote(
            all_linked, all_tags) + "\n"
        anchors = [{"title": t, "locator": t, "summary": "", "tags": []}
                   for t in all_tags]
        mem.write(
            id=rid,
            title="%s 单日记录" % d,
            summary="%s 共 %d 段叙事" % (d, n),
            aliases=[d],
            tags=all_tags,
            linked=all_linked,
            body=full_body,
            created=created,
            updated=date.today().isoformat(),
            anchors=anchors,
            trigger=trigger,
        )
    finally:
        mem.close()
    return rid, n


def _strip_index(body):
    """去掉包末的索引 blockquote（追加新段前清理）。"""
    lines = (body or "").splitlines()
    while lines and lines[-1].strip().startswith("> 索引"):
        lines.pop()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 读取：按日 / 按区间（时间 = 过滤键，非权重）
# ---------------------------------------------------------------------------
def read_day(root, date_str):
    """取某天的单日记录包；无则返回 None。"""
    mem = Memory(root)
    try:
        return mem.read(day_id(date_str))
    finally:
        mem.close()


def days_in_range(root, start=None, end=None):
    """列出 [start, end] 区间内存在的单日包，按日历序升序。

    返回 [(date_str, rid, title), ...]。start/end 任一可省（开区间端）。
    日期比较 = id 后缀字符串比较（ISO 日期字典序即时间序，确定性）。
    """
    start = ensure_date(start) if start else None
    end = ensure_date(end) if end else None
    mem = Memory(root)
    try:
        rows = mem.list_all()
    finally:
        mem.close()
    out = []
    for rid, title, _tags, _updated in rows:
        if not rid.startswith(DAY_PREFIX):
            continue
        d = rid[len(DAY_PREFIX):]
        try:
            d = ensure_date(d)
        except ValueError:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue
        out.append((d, rid, title))
    out.sort()  # 日历序（客观时间顺序，非相关性权重）
    return out


# ---------------------------------------------------------------------------
# 叙事段解析与包内精准搜寻
# ---------------------------------------------------------------------------
def parse_beats(body):
    """把单日包正文解析成叙事段列表（顺序 = 追加顺序，正文即真相）。

    返回 [{"text", "linked", "tags"}, ...]。
    """
    body = body or ""
    beats, last = [], 0
    for m in _BEAT_RE.finditer(body):
        prose = _clean_prose(body[last:m.start()])
        meta = _parse_beat_meta(m.group(1))
        if prose or meta["linked"] or meta["tags"]:
            beats.append({"text": prose, **meta})
        last = m.end()
    return beats


def filter_beats(pkg, q):
    """精准搜寻型：在单日包的叙事段内做确定性关键词匹配。

    匹配面 = 段叙事正文 + 该段 linked + 该段 tags（大小写不敏感子串）。
    不打分、不排序（保持时间顺序）。无 q 则返回全部段。
    """
    ql = (q or "").lower().strip()
    if not ql:
        return parse_beats(pkg.body if pkg else "")
    hits = []
    for b in parse_beats(pkg.body if pkg else ""):
        hay = (b["text"] + " " + " ".join(b["linked"])
               + " " + " ".join(b["tags"])).lower()
        if ql in hay:
            hits.append(b)
    return hits
