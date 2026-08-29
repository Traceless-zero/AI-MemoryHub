# -*- coding: utf-8 -*-
"""pdf_reflow.py —— 论文 PDF 确定性重排管线（hma-ingest 文章/资料分支）。

病症（PyMuPDF 纯文本模式的产物）：
  1. 双栏 PDF 按对象顺序提取 → 视觉顺序错乱（标题跑到摘要后面）
  2. 栏宽处硬换行 → 句子全碎
  3. 标题与正文/页码粘连、标题折行被截断
  4. 零 `##` 锚点 → L2 章级召回整层塌掉

方案（全程确定性，无 LLM）：
  ① 按坐标重提：dict 模式拿块级 bbox，全宽块分段、段内左栏→右栏
  ② 噪声剥除：独立页码块、跨页重复短行（页眉/脚）、
     小字号纯数字 span（≤0.75×正文字号，粘在标题后的页码）——逐条记录清单
  ③ 标题标记（论文体规则，用户 R59 拍板"映射到最小单元"）：
     大章(I. II. / ABSTRACT / INDEX TERMS / REFERENCES) → ##
     小节(1.1) → ###   子小节(1.1.1) → ####
     判据 = 编号正则 + **粗体字体**（不用"句末标点否决"，
     免得《从"小概率奇迹"到"统计必然"》这类引号结尾标题被误杀）；
     标题块**整块**归标题（折行尾巴并回，如 2.6 的"解释"）；
     关键词部分整段一个锚点（不逐词拆）
  ④ 拼段落：行尾无句末标点 → 与下行相连；跨块续拼仅限双栏正文块，
     全宽块（标题/作者/资助行）各自独立成段
  ⑤ 原样校验（铁律护栏）：非空白字符 Counter 必须满足
     raw == new_body + removed_noise，差一个字就 abort
  ⑥ --write 落库：保留 front-matter（linked/tags/created 不动），
     只换 body；锚点用 derive_anchors(max_level=6) 重新派生（全层级细切）

用法：
  python scripts/core/pdf_reflow.py <pdf> --out /tmp/reflow.md            # 试跑出稿
  python scripts/core/pdf_reflow.py <pdf> --write <memory_root> <包相对路径> <事件id>
"""
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_WS = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# ① 视觉顺序重提
# ---------------------------------------------------------------------------

def ordered_blocks(page):
    """按视觉顺序返回 [(block, is_fullwidth), ...]。
    全宽块把页面切成纵向分段；段内先左栏（y 序）后右栏（y 序）。"""
    d = page.get_text("dict")
    blocks = [b for b in d["blocks"] if b.get("type") == 0]
    mid = page.rect.width / 2
    full, cols = [], []
    for b in blocks:
        x0, _, x1, _ = b["bbox"]
        (full if (x0 < mid - 40 and x1 > mid + 40) else cols).append(b)
    full.sort(key=lambda b: b["bbox"][1])

    out, seg_top = [], float("-inf")
    for fb in full + [None]:
        seg_bot = fb["bbox"][1] if fb else float("inf")
        seg = [b for b in cols if seg_top <= b["bbox"][1] < seg_bot]
        left = sorted((b for b in seg if b["bbox"][0] < mid),
                      key=lambda b: b["bbox"][1])
        right = sorted((b for b in seg if b["bbox"][0] >= mid),
                       key=lambda b: b["bbox"][1])
        out.extend((b, False) for b in left + right)
        if fb:
            out.append((fb, True))
            seg_top = fb["bbox"][1]
    return out


def body_font_size(doc):
    """正文主字号 = 全文 span 字号众数（确定性）。"""
    cnt = Counter()
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            if b.get("type"):
                continue
            for ln in b["lines"]:
                for s in ln["spans"]:
                    t = s["text"].strip()
                    if t:
                        cnt[round(s["size"], 1)] += len(t)
    return cnt.most_common(1)[0][0] if cnt else 10.0


# ---------------------------------------------------------------------------
# ② 行提取 + span 级噪声（小字号粘连页码）
# ---------------------------------------------------------------------------

def block_lines(b, base_size, removed, pno):
    """块 → [(text, first_font)]。剥除小字号纯数字 span（粘连页码）。"""
    out = []
    for ln in b.get("lines", []):
        parts, first_font = [], ""
        for sp in ln.get("spans", []):
            t = sp["text"]
            if (t.strip().isdigit() and sp["size"] <= base_size * 0.75):
                removed.append(f"p{pno} 标题/正文粘连页码: '{t.strip()}'")
                continue
            if t.strip() and not first_font:
                first_font = sp.get("font", "")
            parts.append(t)
        t = "".join(parts)
        if t.strip():
            out.append((t, first_font))
    return out


_PAGENO = re.compile(r"^\s*(?:\d{1,3}|[ivxlc]{1,6})\s*$", re.I)


def block_noise(pages, base_size):
    """块级噪声：独立页码块 + ≥3 页重复短行（页眉/脚）。"""
    seen = {}
    texts = {}
    for pi, blocks in enumerate(pages):
        for bi, (b, _) in enumerate(blocks):
            txt = " ".join("".join(sp["text"] for sp in ln["spans"])
                           for ln in b.get("lines", [])).strip()
            texts[(pi, bi)] = txt
            if 0 < len(txt) <= 60:
                seen.setdefault(txt, set()).add(pi)
    noise, removed = set(), []
    for (pi, bi), txt in texts.items():
        if not txt:
            continue
        if _PAGENO.match(txt):
            noise.add((pi, bi))
            removed.append(f"p{pi+1} 独立页码块: '{txt}'")
        elif len(seen.get(txt, ())) >= 3:
            noise.add((pi, bi))
            removed.append(f"p{pi+1} 页眉/脚: '{txt}'")
    return noise, removed


# ---------------------------------------------------------------------------
# ③ 标题标记（论文体：最小单元映射，粗体判据）
# ---------------------------------------------------------------------------

_H_SPECIAL = re.compile(
    r"^(ABSTRACT\s*/\s*摘要|INDEX\s*TERMS\s*/\s*关键词|"
    r"REFERENCES\s*/\s*参考文献|ACKNOWLEDGMENTS?\s*/\s*致谢)\s*")
_H_ROMAN = re.compile(r"^[IVX]{1,4}\.\s+\S")
_H_SUBSUB = re.compile(r"^\d+\.\d+\.\d+\s+\S")
_H_SUB = re.compile(r"^\d+\.\d+\s+\S")
_H_REF = re.compile(r"^(REFERENCES|参考文献|ACKNOWLEDG|致谢)", re.I)


def _is_bold(font):
    return "Bold" in (font or "")


def classify_heading(text, font):
    """返回 (level, heading_text, remainder)；非标题 → (0, None, text)。"""
    t = text.strip()
    m = _H_SPECIAL.match(t)
    if m:  # ABSTRACT/关键词可能与正文粘连：切开
        return 2, m.group(1).strip(), t[m.end():].strip()
    if len(t) <= 90 and _is_bold(font):
        if _H_ROMAN.match(t) or _H_REF.match(t):
            return 2, t, ""
        if _H_SUBSUB.match(t):
            return 4, t, ""
        if _H_SUB.match(t):
            return 3, t, ""
    return 0, None, text


# ---------------------------------------------------------------------------
# ④ 拼段落
# ---------------------------------------------------------------------------

_SENT_END = re.compile(r"[。！？!?.”\"』」]$")


def _join(a, b):
    if not a:
        return b
    if a[-1].isascii() and a[-1].isalnum() and b and b[0].isascii() and b[0].isalnum():
        return a + " " + b
    return a + b


def reflow(pdf_path):
    """返回 (markdown_body, removed_list, raw_counter)。"""
    import fitz  # PyMuPDF（延迟导入：模块加载零依赖，仅处理 PDF 时需要）
    doc = fitz.open(pdf_path)
    base = body_font_size(doc)
    pages = [ordered_blocks(p) for p in doc]
    noise, removed = block_noise(pages, base)

    raw_cnt = Counter()
    chunks = []                  # (kind, text, fullwidth)
    for pi, blocks in enumerate(pages):
        for bi, (b, fw) in enumerate(blocks):
            # raw 基准：块内全部 span（含即将剥除的噪声）
            for ln in b.get("lines", []):
                for sp in ln["spans"]:
                    raw_cnt.update(_WS.sub("", sp["text"]))
            if (pi, bi) in noise:
                continue
            lines = block_lines(b, base, removed, pi + 1)
            if not lines:
                continue
            # 标题块整块归标题：首行命中 → 块内所有行并成一个标题
            lvl, head, rest = classify_heading(*lines[0])
            if lvl and not rest:
                whole = head
                for t, _f in lines[1:]:
                    whole = _join(whole, t.strip())
                chunks.append((f"h{lvl}", whole, fw))
                continue
            para = ""
            for t, f in lines:
                lvl, head, rest = classify_heading(t, f)
                if lvl:
                    if para.strip():
                        chunks.append(("p", para.strip(), fw))
                        para = ""
                    chunks.append((f"h{lvl}", head, fw))
                    para = rest
                else:
                    para = _join(para, t.strip())
            if para.strip():
                chunks.append(("p", para.strip(), fw))
    doc.close()

    # 跨块续拼：上块是未完句正文时续拼；全宽↔双栏之间不互拼
    # （全宽块间也拼：论文大标题常被折成两个全宽块，如"…无因果/契合"…"）
    merged = []
    for kind, text, fw in chunks:
        if (kind == "p" and merged
                and merged[-1][0] == "p" and merged[-1][2] == fw
                and not _SENT_END.search(merged[-1][1])):
            merged[-1][1] = _join(merged[-1][1], text)
        else:
            merged.append([kind, text, fw])

    out = []
    for kind, text, _fw in merged:
        out.append(text if kind == "p" else "#" * int(kind[1]) + " " + text)
    return "\n\n".join(out) + "\n", removed, raw_cnt


# ---------------------------------------------------------------------------
# ⑤ 原样校验
# ---------------------------------------------------------------------------

def verify(body, removed, raw_cnt):
    got = Counter(_WS.sub("", body))
    for r in removed:
        m = re.search(r": '(.*)'$", r)
        if m:
            got.update(_WS.sub("", m.group(1)))
    # 标题的 # 是新增 markdown 语法，不算内容
    extra_hash = got.get("#", 0) - raw_cnt.get("#", 0)
    if extra_hash > 0:
        got["#"] -= extra_hash
    plus = {c: n for c, n in (got - raw_cnt).items() if n}
    minus = {c: n for c, n in (raw_cnt - got).items() if n}
    return plus, minus


# ---------------------------------------------------------------------------
# ⑥ 落库
# ---------------------------------------------------------------------------

def write_back(memory_root, pkg_rel, event_id, body):
    from hma.hma_core import Memory
    from hma.hma_core import derive_anchors
    root = os.path.join(os.path.abspath(memory_root), *pkg_rel.split("/"))
    m = Memory(root)
    pkg = m.read(event_id)
    if not pkg:
        raise SystemExit(f"[abort] 事件包不存在: {event_id} @ {pkg_rel}")
    anchors = derive_anchors(body, max_level=6)   # 全层级细切：最小单元锚点
    m.write(pkg.id, pkg.title, pkg.summary, pkg.aliases, pkg.tags,
            pkg.linked, body, created=pkg.created, anchors=anchors,
            trigger="pdf_reflow")
    m.close()
    return len(anchors)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(2)
    pdf = args[0]
    body, removed, raw_cnt = reflow(pdf)
    hl = body.splitlines()
    print(f"[reflow] ## {sum(1 for l in hl if l.startswith('## '))} 个，"
          f"### {sum(1 for l in hl if l.startswith('### '))} 个，"
          f"#### {sum(1 for l in hl if l.startswith('#### '))} 个，"
          f"总字符 {len(_WS.sub('', body))}")
    print(f"[noise] 剥除 {len(removed)} 条：")
    for r in removed:
        print("   -", r)
    plus, minus = verify(body, removed, raw_cnt)
    if plus or minus:
        print(f"[FAIL] 原样校验不通过！多出: {plus} 缺失: {minus}")
        raise SystemExit(1)
    print("[verify] 原样校验通过：raw == body + removed（非空白字符逐字相等）")

    if "--write" in args:
        i = args.index("--write")
        memory_root, pkg_rel, event_id = args[i+1:i+4]
        n = write_back(memory_root, pkg_rel, event_id, body)
        print(f"[write] 已落库 {event_id}（锚点 {n} 个，max_level=6）")
    elif "--out" in args:
        out = args[args.index("--out") + 1]
        with open(out, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"[out] 试跑稿: {out}")


if __name__ == "__main__":
    main()
