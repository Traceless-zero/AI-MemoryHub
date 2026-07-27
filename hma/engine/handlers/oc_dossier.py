# -*- coding: utf-8 -*-
"""mode: oc_dossier —— 结构化 dossier → 按三层铁律确定性切包。

输入：一份「已结构化」的 dossier markdown（硬数据卡 + 分节），
      在源文件文档头用 `source:` 指向它（或用 body_ref）。
输出：<id>-base（必有且仅 1）/ <id>-origin（超长背景才分立）/ <id>-ext（合并）

切片规则（忠实于 oc-dossier 三层铁律，纯确定性，无 LLM）：
  · 数据卡（首个 `##` 之前）→ 基础包
  · 形象 / 性格 / 信条 / 语气 → 基础包
  · 背景 / 人生经历：短则并入基础包；> ORIGIN_LONG 字才分立故事包
  · 能力 / 装备 / 参与事件 / 人物关系 → 合并进 1 个拓展包

注：本 handler 是 skills/oc-dossier/references/dossier_build.py 的
    引擎化提升版。技能仍保留自带副本以便独立分发；引擎这份为库内规范实现。
"""

import os
import re

from ..registry import register
from ...hma_core import Memory

ORIGIN_LONG = 600

BASE_PERSONA_KW = ["形象", "外貌", "相貌", "外表", "外观",
                   "性格", "信条", "行事准则", "行事风格", "行事调性",
                   "语言调性", "语言风格", "人格", "性情", "语气"]
ORIGIN_KW = ["背景故事", "背景", "人生经历", "生平", "来历", "身世", "经历", "传记"]
EXT_KW = ["能力装备", "能力", "装备", "技能", "武装", "功法", "异能", "武器",
          "参与事件", "重大事件", "战绩", "事迹",
          "人物关系", "关系", "相关人物", "羁绊", "交际", "人际关系"]

_TOP = re.compile(r'^##\s+(.+?)\s*$')
_NAME_KEYS = ["本名", "姓名", "名字", "真名", "全名"]


def _split_sections(text):
    lines = text.splitlines()
    idx = next((i for i, ln in enumerate(lines) if _TOP.match(ln)), None)
    if idx is None:
        return text.strip() + "\n", []
    data_card = "\n".join(lines[:idx]).strip() + "\n"
    sections, cur_title, cur_buf = [], None, []
    for ln in lines[idx:]:
        m = _TOP.match(ln)
        if m:
            if cur_title is not None:
                sections.append((cur_title, "\n".join(cur_buf).strip()))
            cur_title, cur_buf = m.group(1), []
        elif cur_title is not None:
            cur_buf.append(ln)
    if cur_title is not None:
        sections.append((cur_title, "\n".join(cur_buf).strip()))
    return data_card, sections


def _classify(title):
    if any(kw in title for kw in BASE_PERSONA_KW):
        return "base"
    if any(kw in title for kw in ORIGIN_KW):
        return "origin"
    return "ext"  # 兜底并入拓展包，避免丢失


def _find_name(data_card, sections, fallback):
    blob = data_card + "\n" + "\n".join(t for t, _ in sections)
    for ln in blob.splitlines():
        s = ln.strip()
        for key in _NAME_KEYS:
            m = re.match(r'^\|?\s*%s\s*[:：]\s*(.+?)\s*\|?\s*$' % re.escape(key), s)
            if m:
                return m.group(1).strip().strip("|").strip()
    return fallback


def slice_dossier(text, char_id, name=None):
    """把结构化 dossier 文本切成 {base, origin, ext} 三段正文（origin/ext 可空）。"""
    data_card, sections = _split_sections(text)
    disp = name or _find_name(data_card, sections, char_id)
    base_parts, origin_parts, ext_parts = [data_card], [], []
    for title, body in sections:
        block = "## %s\n\n%s" % (title, body) if body else "## %s" % title
        kind = _classify(title)
        if kind == "base":
            base_parts.append(block)
        elif kind == "origin":
            (base_parts if len(body) <= ORIGIN_LONG else origin_parts).append(block)
        else:
            ext_parts.append(block)
    return disp, {
        "base": "\n\n".join(p for p in base_parts if p.strip()) + "\n",
        "origin": ("\n\n".join(origin_parts) + "\n") if origin_parts else "",
        "ext": ("\n\n".join(ext_parts) + "\n") if ext_parts else "",
    }


@register("oc_dossier")
def handle_oc_dossier(doc, *, root_override=None, base_dir=None,
                      repo_root=None, trigger="engine.derive"):
    meta = doc.meta
    char_id = meta.get("id") or meta.get("name")
    if not char_id:
        raise ValueError("oc_dossier 源缺少 id")
    src = meta.get("source")
    base_d = os.path.dirname(doc.path or "")
    if src:
        src_path = src if os.path.isabs(src) else os.path.join(base_d, src)
        with open(src_path, encoding="utf-8") as f:
            text = f.read()
    elif doc.packs:
        # 也允许把 dossier 正文直接内联在第一个 pack 的 body 里
        text = doc.resolve_body(doc.packs[0], base_dir=base_d)
    else:
        raise ValueError("oc_dossier 源缺少 source: 或内联正文")

    root = root_override or (
        meta["root"] if os.path.isabs(meta.get("root", "")) else
        os.path.normpath(os.path.join(repo_root or ".",
                                      meta.get("root") or os.path.join("memory", "原创角色", char_id)))
    )
    disp, bodies = slice_dossier(text, char_id, name=meta.get("name"))

    mem = Memory(root)
    packs = []
    try:
        base_title = "%s（%s）" % (disp, char_id) if char_id != disp else disp
        mem.write(char_id + "-base", base_title,
                  "基础包：硬数据卡 + 形象 + 行事调性（+短背景）。扮演最小可运行单元。",
                  aliases=[disp, char_id], tags=["oc", "角色档案", "基础包", "索引"],
                  body=bodies["base"], trigger=trigger)
        packs.append(char_id + "-base")
        if bodies["origin"]:
            mem.write(char_id + "-origin", "%s · 背景故事" % disp,
                      "故事包：人生经历 / 背景（超长叙事分立）",
                      aliases=["背景", "故事", "人生经历"], tags=["oc", "故事包"],
                      body=bodies["origin"], trigger=trigger)
            packs.append(char_id + "-origin")
        if bodies["ext"]:
            mem.write(char_id + "-ext", "%s · 拓展" % disp,
                      "拓展包：能力 / 装备 / 参与事件 / 人物关系（合并）",
                      aliases=["拓展", "能力", "关系", "装备", "事件"], tags=["oc", "拓展包"],
                      body=bodies["ext"], trigger=trigger)
            packs.append(char_id + "-ext")
        for pid in packs[1:]:
            mem.link(char_id + "-base", pid)
        mem.rebuild()
    finally:
        mem.close()
    return packs
