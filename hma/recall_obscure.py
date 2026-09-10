# -*- coding: utf-8 -*-
"""
AIMH 召回机械层（recall_obscure）—— 沙箱实验稿 consolidation。

收编自 to_delete/ 下沙箱原型（已验证、被生产 obscure_recall 内联重写的版本）：
  · sandbox_obscure_slim.py      —— 不起眼物件 / 长尾细节追问的章内局部倒排 + 重叠合并瘦身
  · sandbox_dk_base_half.py      —— dK 裁切基准 = BASE_UNIT×0.5 联动验证（设计稿，派生式未采用）
  · sandbox_dk_cutoff_compare.py —— CUTOFF_GAP_FLOOR 50 vs 75 真实 hit@5 对比（已跑，选 75）

本模块是零依赖确定性机械层（re / math），被 hma_core 的 obscure_recall 调用，
消除「沙箱原型逻辑被生产内联重复」的漂移风险——改一处即全链路一致。

铁律（上下文）：
  · 机械层只去冗余、不替 AI 选段；不同语境段文本不重叠必须保留。
  · merge 阈值 0.5：交集占较小区间比例 > 此值即合并（同处被切重才合并）。
  · dK waterfall_cut：相邻锚点分差 d_k > floor 即从该处单向裁切，非绝对分阈值。
"""
import re
import math

from . import scoring_coeffs as C

# ---- merge 默认阈值（与 obscure_recall 内联版一致） ----
OVERLAP_RATIO = 0.5


# ---------- 章级切分 ----------
def split_chapters(body):
    """按 ##~###### 切分正文为 [(标题, 该章正文), ...]。复用 derive_anchors 的标题正则。"""
    lines = (body or "").splitlines()
    heads = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{2,6})\s+(.*)$", ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    out = []
    for k, (i, lvl, title) in enumerate(heads):
        end = len(lines)
        for j in range(k + 1, len(heads)):
            if heads[j][1] <= lvl:
                end = heads[j][0]
                break
        out.append((title, "\n".join(lines[i:end])))
    return out


# ---------- 局部倒排 ----------
def local_inverted(text, token):
    """返回 token 在 text 中所有出现的起始位置列表（re.escape 防正则元字符）。"""
    return [m.start() for m in re.finditer(re.escape(token), text)]


# ---------- 区间重叠合并 ----------
def merge_intervals(pairs, ratio=OVERLAP_RATIO):
    """输入 [(s, e), ...]，按起点排序后重叠合并：交集占较小区间比例 > ratio 即并。
    返回合并后 [(s, e), ...]。不同语境（不重叠）区间保留。"""
    if not pairs:
        return []
    ivs = sorted(pairs, key=lambda x: x[0])
    merged = [list(ivs[0])]
    for s, e in ivs[1:]:
        ps, pe = merged[-1]
        inter = max(0, min(pe, e) - max(ps, s))
        smaller = min(pe - ps, e - s)
        if smaller > 0 and inter / smaller > ratio:
            merged[-1][0] = min(ps, s)
            merged[-1][1] = max(pe, e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def slim_segments(raw_intervals, ratio=OVERLAP_RATIO):
    """不起眼物件瘦身主入口。

    raw_intervals: [(rid, ctitle, about, s, e, near), ...]
                   其中 s/e 为 obj_token 命中点 ±window 的字符窗口（由调用方预计算）。
    对同 (rid, ctitle) 内的区间做重叠合并（去同处被切重的冗余），保留不重叠的不同语境段。
    合并顺序（sorted((rid, ctitle, s))）是生产唯一实现——hma_core.obscure_recall
    直接调用本函数，改动排序键会直接改变 top_k 截断结果。
    返回合并后 [(rid, ctitle, about, s, e, near), ...]。
    """
    grouped = {}
    for iv in raw_intervals:
        grouped.setdefault((iv[0], iv[1]), []).append(iv)
    merged = []
    for key in sorted(grouped.keys()):          # 按 (rid, ctitle) 排序，对齐内联版
        rid, ctitle = key
        ivs = grouped[key]
        pairs = [(iv[3], iv[4]) for iv in ivs]
        mp = merge_intervals(pairs, ratio=ratio)
        for (s, e) in mp:
            # about/near 同 (rid,ctitle) 内恒定，取覆盖该合并区间的首个 iv 元数据
            src = next((iv for iv in ivs if iv[3] <= s and iv[4] >= e), ivs[0])
            merged.append((rid, ctitle, src[2], s, e, src[5]))
    return merged


# ---------- 章内字符区间切片 ----------
def chapter_slice(body, chapter_title, start, end):
    """取某章正文里 [start,end] 字符区间，跨标题边界时截断到该章内。"""
    if not body:
        return ""
    lines = body.splitlines()
    cstart = None
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{2,6})\s+(.*)$", ln)
        if m and chapter_title in m.group(2):
            cstart, level = i, len(m.group(1))
            break
    if cstart is None:
        return body[start:end]
    cend = len(lines)
    for j in range(cstart + 1, len(lines)):
        m = re.match(r"^(#{2,6})\s+", lines[j])
        if m and len(m.group(1)) <= level:
            cend = j
            break
    chap_text = "\n".join(lines[cstart:cend])
    cs, ce = max(start, 0), min(end, len(chap_text))
    return chap_text[cs:ce]




# ---------- dK 瀑布裁切（与召回侧内联版行为一致） ----------
def waterfall_cut(entries, floor):
    """entries[k][4] = 锚点原始分（_anchor_score 量级）；相邻 d_k > floor 处单向裁切、
    返回 entries[:k+1]，全程 d_k <= floor 返回全表。非绝对分阈值、非逐段裁切。"""
    for k in range(len(entries) - 1):
        dk = entries[k][4] - entries[k + 1][4]
        if dk > floor:
            return entries[:k + 1]
    return entries


