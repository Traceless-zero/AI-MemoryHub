# -*- coding: utf-8 -*-
"""fm_yaml —— FM 手写 YAML 子集解析器（零依赖、fail-closed）。

收编自 hma_core.EventPackage 的 11 个 staticmethod（S1 拆分，2026-09-07）：
缩进层级解析 + 单行值解析，专吃 AIMH front-matter，不支持通用 YAML。
EventPackage 上以 staticmethod 别名绑定回原名字（EventPackage._parse_fm 等），
调用方零改动；解析行为由 regress_fm_yaml.py（6 例护栏）+ regress_fm_schema_kw.py 把守。

fail-closed 口径（2026-09-07）：FM 是唯一权威源，遇到不支持的写法一律显式
ValueError，绝不静默产出错误数据——流式 {…}、引号未闭合、\\u/\\x 转义。
"""

import json

# 特殊字段：单行值优先按 JSON 解析（V2 字典/数组），失败回退简易列表解析
_FM_SPECIAL = {"anchors", "features", "person", "location", "topic"}
_FM_LIST = {"tags", "linked", "anchors"}   # 空 block → []
_FM_DICT = {"person", "location", "topic"}  # 空 block → {}


def strip_comment(s):
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


def scalar_or_json(v):
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
            # 未引号中文列表（[示例角色]）退回简易逗号切分，
            # 与 parse_value 行为一致，避免 inline 列表被读成裸字符串。
            return parse_value(v)
    return v


def parse_value(v):
    # 简易列表/标量解析：兼容旧式未引号中文列表 [示例角色]。
    v = v.strip()
    # fail-closed（2026-09-07）：不支持的写法一律显式报错。
    # FM 是唯一权威源，静默产出错误数据无人能察觉，宁可崩不可错。
    if v.startswith("{"):
        raise ValueError(
            "FM 不支持流式花括号 {…}（会静默丢字段），请改用缩进写法：%r" % v[:40])
    if v[:1] in ('"', "'"):
        q = v[0]
        if len(v) < 2 or v[-1] != q:
            raise ValueError("FM 引号未闭合（疑似字面多行串）：%r" % v[:40])
        inner = v[1:-1]
        if "\\" in inner:
            if "\\u" in inner or "\\x" in inner:
                raise ValueError("FM 暂不支持 \\u / \\x 转义：%r" % v[:40])
            inner = (inner.replace("\\\\", "\x00")
                          .replace('\\"', '"').replace("\\'", "'")
                          .replace("\\n", "\n").replace("\\t", "\t")
                          .replace("\x00", "\\"))
        return inner
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


def parse_inline(key, val):
    # 单行值：特殊字段优先 JSON（V2 字典/数组），失败回退简易列表解析。
    try:
        return json.loads(val)
    except Exception:
        return parse_value(val)


def is_kv(s):
    return ":" in s


def empty_default(key):
    if key in _FM_LIST:
        return []
    if key in _FM_DICT:
        return {}
    return ""


def parse_seq(items, start, indent):
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
        if is_kv(body):
            # 映射项：首行 = body（在 indent），后续更深层归它
            sub = [(indent, body)]
            k = i + 1
            while k < n and items[k][0] > indent:
                sub.append(items[k])
                k += 1
            # 列表项的子键比「- 」深一级，需把首行重定基到子键缩进，
            # 否则 parse_mapping 会把更深层子键当「超出 base」跳过。
            child_indent = min((it[0] for it in sub[1:]), default=indent)
            sub = [(child_indent, body)] + sub[1:]
            val, _ = parse_mapping(sub, 0, child_indent)
            seq.append(val)
            i = k
        else:
            seq.append(scalar_or_json(body))
            i += 1
    return seq, i


def parse_mapping(items, start, indent):
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
            d[key] = scalar_or_json(val)
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
                v, _ = parse_seq(sub, 0, sub[0][0])
                d[key] = v
            else:
                v, _ = parse_mapping(sub, 0, sub[0][0])
                d[key] = v
            i = k
    return d, i


def parse_node(items, start, indent):
    content = items[start][1]
    if content.startswith("- "):
        return parse_seq(items, start, indent)
    return parse_mapping(items, start, indent)


def normalize_anchor_kws(anchors):
    """锚点 keywords 归一化：若字段是「长得像 JSON 数组的字符串」（双编码
    畸形），解码为真列表；其余原样返回。覆盖 from_markdown / from_markdown_fm_only
    两条读取路径（二者共用 parse_fm），使引擎与 block 序列化口径一致。"""
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


def parse_fm(text):
    # 逐行 tokenize：去空行/全注释行，剥离行尾注释，记录缩进。
    items = []
    for ln in text.splitlines():
        if not ln.strip():
            continue
        if ln.lstrip().startswith("#"):
            continue
        ind = len(ln) - len(ln.lstrip(" "))
        content = strip_comment(ln.strip())
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
            data[key] = (parse_inline(key, val)
                         if key in _FM_SPECIAL
                         else parse_value(val))
            i += 1
        else:
            # block 换行式：收集后续更深层行
            j = i + 1
            block = []
            while j < n and items[j][0] > base:
                block.append(items[j])
                j += 1
            if not block:
                data[key] = empty_default(key)
            else:
                v, _ = parse_node(block, 0, block[0][0])
                data[key] = v
            i = j
    if "anchors" in data:
        data["anchors"] = normalize_anchor_kws(data["anchors"])
    return data
