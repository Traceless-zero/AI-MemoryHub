# -*- coding: utf-8 -*-
"""daylog —— 单日记录包（时间轴索引层，叙事型）。

单 daylog 路线（daylog设计.md）：一天一个文件 memory/日志/daylog-YYYY-MM-DD.md，
AI 只 append 一条 beat（标题 + touched + linked + tags + 正文），不做任何「归到
哪个项目/模块」的路由判断。语义召回由 AIMH 跨所有 .md 扫锚点完成，与「写在哪」
无关；daylog 仅作时间序跳转入口。

本模块是引擎侧 daylog 读写助手，供 context compaction / 周期梳理等子系统调用
（scripts/core/compact.py、scripts/core/periodic_review.py）。写入严格走 FM-V2：
   person/location/topic 为 {规范名:[变体]} 字典；event_date 为归属日期；
   pkage_created/pkage_updated 取代 created/updated；anchors 仅 {Chapter,about,keywords}；
   不写 aliases / features / locator；title 由文件名机械派生（==daylog-YYYY-MM-DD，AI 不传入，写入工具自动填充）。
"""
import os
import re
from datetime import date

from .hma_core import Memory

DAY_PREFIX = "日志/daylog-"

_BEAT_RE = re.compile(r"<!--\s*beat\s*(.*?)\s*-->", re.S)
_META_KV = re.compile(r"(\w+)\s*:\s*([^<]*?)(?=\s+\w+:|$)")


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
    linked, tags, btype = [], [], "event"
    for k, v in _META_KV.findall(s or ""):
        if k == "linked":
            linked = _split_csv(v)
        elif k == "tags":
            tags = _split_csv(v)
        elif k == "type":
            btype = v.strip() or "event"
    return {"linked": linked, "tags": tags, "type": btype}


def _index_blockquote(linked, tags):
    return ("> 索引 · linked: [%s] · tags: [%s]"
            % (", ".join(linked), ", ".join(tags)))


def _strip_index(body):
    """去掉包末的索引 blockquote（追加新段前清理）。"""
    lines = (body or "").splitlines()
    while lines and lines[-1].strip().startswith("> 索引"):
        lines.pop()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 写入：追加一段叙事（FM-V2 合规）
# ---------------------------------------------------------------------------
def append_beat(root, text, linked=None, tags=None,
                date_str=None, beat_type="event", trigger="daylog.append"):
    """向某天的单日记录包追加一段叙事（FM-V2 合规写入）。

    root      仓库记忆根（如 memory；daylog 包位于 memory/日志/，
              id 命名空间为 日志/daylog-YYYY-MM-DD，由 path 派生）
    text      一段叙事（必填）：描述这天发生的一件事 / 一个进展
    linked    该段链接到的主题包 id（列表或逗号分隔串）
    tags      该段关键词 tag（列表或逗号分隔串）
    date_str  归属日期 YYYY-MM-DD；缺省今天
    beat_type 段类型：'event'（收录/大事件，默认）| 'query'（用户查询观测）

    返回 (rid, n_beats)。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("叙事内容不能为空")
    d = ensure_date(date_str or date.today().isoformat())
    rid = day_id(d)
    linked = _split_csv(linked)
    tags = _split_csv(tags)
    meta = "type:%s linked:%s tags:%s" % (beat_type, ",".join(linked), ",".join(tags))
    beat_block = "%s\n<!--beat %s-->" % (text, meta)

    mem = Memory(root)
    try:
        pkg = mem.read(rid)
        if pkg:
            body = _strip_index(pkg.body)
            new_body = body.rstrip() + "\n\n" + beat_block
            all_linked = _dedup(pkg.linked + linked)
            all_tags = _dedup(pkg.tags + tags)
            pk_created = pkg.created          # 已有包：保留原收录日期
        else:
            head = "# %s 工作日志" % d
            new_body = head + "\n\n" + beat_block
            all_linked, all_tags = linked, tags
            pk_created = d                     # 新包：收录日期 = 归属日
        n = len(parse_beats(new_body))
        full_body = new_body.rstrip() + "\n\n" + _index_blockquote(
            all_linked, all_tags) + "\n"
        # FM-V2 写入：四要素字典 + event_date + pkage_*；title 由文件名(id 的 basename)机械派生，AI 不传入；不写 aliases/locator
        mem.write(
            id=rid,
            title=os.path.basename(rid),          # == daylog-YYYY-MM-DD，与磁盘文件名严格一致（单一真相源）
            summary="%s 共 %d 段叙事" % (d, n),
            tags=all_tags,
            linked=all_linked,
            person=[{"用户": ["我", "用户本人"]}],
            event_date=d,
            location=[],
            topic=[],
            body=full_body,
            anchors=[],                        # 不含 locator；rebuild 时可派生
            pkage_created=pk_created,
            pkage_updated=date.today().isoformat(),
            trigger=trigger,
        )
    finally:
        mem.close()
    return rid, n


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

    注意：`mem.list_all()` 返回的 rid 是 basename（如 daylog-2026-08-13），
    与 read 用的 path-derived id（日志/daylog-2026-08-13）不一致；此处按
    basename 判 `daylog-` 前缀，日期从 basename 后缀抽取。
    """
    start = ensure_date(start) if start else None
    end = ensure_date(end) if end else None
    mem = Memory(root)
    try:
        rows = mem.list_all()
    finally:
        mem.close()
    base_prefix = os.path.basename(DAY_PREFIX)   # "daylog-"
    out, seen_d = [], set()
    for rid, title, _tags, _updated in rows:
        base = os.path.basename(rid)
        if not base.startswith(base_prefix):
            continue
        d = base[len(base_prefix):]
        try:
            d = ensure_date(d)
        except ValueError:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue
        # 同一天物理文件可能因 package_id 不一致（'日志' vs ''）在
        # 索引里出现两行 → 同一日只应出现一次（时间轴索引层语义）。
        if d in seen_d:
            continue
        seen_d.add(d)
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
