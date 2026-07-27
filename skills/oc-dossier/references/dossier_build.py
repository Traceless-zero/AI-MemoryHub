# -*- coding: utf-8 -*-
"""OC 结构化 dossier → 按三层铁律落 3 包（确定性，无 LLM）。

=====================================================================
自动路落库器：配合 oc-dossier（store 分支）使用。
输入：一份「已结构化」的 dossier markdown（硬数据卡 + 分节），
      即 oc_classify 判定为 structured 的来源。
输出：memory/原创角色/<id>/ 下的（事件 .md 直接置于包目录，R50 移除 events/）
      - <id>-base   （必有且仅 1 个：硬数据卡 + 形象 + 行事调性(+短背景)）
      - <id>-origin （铁律②：背景/人生经历「超长」才分立为故事包）
      - <id>-ext    （铁律③：能力/事件/关系合并为 1 个拓展包）

切片规则（忠实于 oc-dossier 三层铁律）：
  · 数据卡（首个 `##` 之前的内容）永远进基础包。
  · 形象 / 性格 / 信条 / 行事调性 / 语气 → 基础包。
  · 背景 / 人生经历 / 来历 / 身世 → 短则并入基础包；
    纯文本超过 ORIGIN_LONG(600) 字才分立为故事包。
  · 能力 / 装备 / 参与事件 / 人物关系 → 合并进 1 个拓展包，
    原 `###` 子标题保留为段落，供 invoke 惰性召回。

不调 LLM、不做理解，只做确定性切片与落库。
=====================================================================

运行（需在能 import hma.hma_core 的目录，如 hma/ 下）：
  python dossier_build.py --id nerein --source path/to/nerein.md
  python dossier_build.py --id nerein --source path/to/nerein.md \
                          --root memory/原创角色/nerein --name "涅蕾因"
"""

import os
import re
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
# 技能位于 hma/skills/oc-dossier/references/，上溯 3 级即 hma/
_HMA_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
if os.path.isdir(os.path.join(_HMA_ROOT, "hma")) and _HMA_ROOT not in sys.path:
    sys.path.insert(0, _HMA_ROOT)

from hma.hma_core import Memory  # noqa: E402

ORIGIN_LONG = 600  # 背景超过此字数才分立故事包

BASE_PERSONA_KW = ["形象", "外貌", "相貌", "外表", "外观",
                    "性格", "信条", "行事准则", "行事风格",
                    "语言调性", "语言风格", "人格", "性情", "语气"]
ORIGIN_KW = ["背景故事", "背景", "人生经历", "生平", "来历", "身世", "经历", "传记"]
EXT_KW = ["能力装备", "能力", "装备", "技能", "武装", "功法", "异能", "武器",
          "参与事件", "重大事件", "战绩", "事迹",
          "人物关系", "关系", "相关人物", "羁绊", "交际", "人际关系"]

TOP_SECTION_RE = re.compile(r'^##\s+(.+?)\s*$')
IDENTITY_NAME_KEYS = ["本名", "姓名", "名字", "真名", "全名"]


def _split_sections(text):
    """返回 (data_card_str, [(title, body), ...])。
    data_card = 首个 `##` 之前的所有内容（含标题与硬数据卡）。
    各 section 保留内部 `###` 子标题。"""
    lines = text.splitlines()
    # 找首个 `##` 行
    idx = None
    for i, ln in enumerate(lines):
        if TOP_SECTION_RE.match(ln):
            idx = i
            break
    if idx is None:
        # 没有任何 `##`：整份当作数据卡 + 单包
        return text.strip() + "\n", []
    data_card = "\n".join(lines[:idx]).strip() + "\n"
    sections = []
    cur_title, cur_buf = None, []
    for ln in lines[idx:]:
        m = TOP_SECTION_RE.match(ln)
        if m:
            if cur_title is not None:
                sections.append((cur_title, "\n".join(cur_buf).strip()))
            cur_title = m.group(1)
            cur_buf = []
        else:
            if cur_title is not None:
                cur_buf.append(ln)
    if cur_title is not None:
        sections.append((cur_title, "\n".join(cur_buf).strip()))
    return data_card, sections


def _classify_section(title):
    if any(kw in title for kw in BASE_PERSONA_KW):
        return "base"
    if any(kw in title for kw in ORIGIN_KW):
        return "origin"
    if any(kw in title for kw in EXT_KW):
        return "ext"
    # 兜底：无法归类的分节并入拓展包（避免丢失）
    return "ext"


def _find_name(data_card, sections, fallback):
    """从数据卡 / 首个分节里找 本名/姓名。"""
    blob = data_card + "\n" + "\n".join(t for t, _ in sections)
    # 键值对 / 表 取 本名/姓名
    for ln in blob.splitlines():
        s = ln.strip()
        for key in IDENTITY_NAME_KEYS:
            m = re.match(r'^\|?\s*%s\s*[:：]\s*(.+?)\s*\|?\s*$' % re.escape(key), s)
            if m:
                return m.group(1).strip().strip("|").strip()
    return fallback


def build(source, char_id, name=None, root=None):
    with open(source, encoding="utf-8") as f:
        text = f.read()
    data_card, sections = _split_sections(text)
    disp = name or _find_name(data_card, sections, char_id)

    base_parts, origin_parts, ext_parts = [data_card], [], []
    for title, body in sections:
        kind = _classify_section(title)
        block = "## %s\n\n%s" % (title, body) if body else "## %s" % title
        if kind == "base":
            base_parts.append(block)
        elif kind == "origin":
            # 短背景并入基础包；超长分立故事包
            if len(body) <= ORIGIN_LONG:
                base_parts.append(block)
            else:
                origin_parts.append(block)
        else:  # ext
            ext_parts.append(block)

    base_body = "\n\n".join(p for p in base_parts if p.strip()) + "\n"
    packs = []

    # ① 基础包（铁律①：必有且仅 1 个）
    base_title = "%s（%s）" % (disp, char_id) if char_id != disp else disp
    m_root = root or os.path.join("memory", "原创角色", char_id)
    mem = Memory(m_root)
    mem.write(char_id + "-base", base_title,
              "基础包：硬数据卡 + 形象 + 行事调性（+短背景）。扮演最小可运行单元。",
              aliases=[disp, char_id],
              tags=["oc", "角色档案", "基础包", "索引"],
              body=base_body)
    packs.append(char_id + "-base")

    # ② 故事包（铁律②：超长背景才分立）
    if origin_parts:
        origin_body = "\n\n".join(origin_parts) + "\n"
        mem.write(char_id + "-origin", "%s · 背景故事" % disp,
                  "故事包：人生经历 / 背景（超长叙事分立）",
                  aliases=["背景", "故事", "人生经历"],
                  tags=["oc", "故事包"],
                  body=origin_body)
        packs.append(char_id + "-origin")

    # ③ 拓展包（铁律③：能力/事件/关系合并 1 个）
    if ext_parts:
        ext_body = "\n\n".join(ext_parts) + "\n"
        mem.write(char_id + "-ext", "%s · 拓展" % disp,
                  "拓展包：能力 / 装备 / 参与事件 / 人物关系（合并）",
                  aliases=["拓展", "能力", "关系", "装备", "事件"],
                  tags=["oc", "拓展包"],
                  body=ext_body)
        packs.append(char_id + "-ext")

    # 关联：基础包 ↔ 其它包
    for pid in packs[1:]:
        mem.link(char_id + "-base", pid)
    mem.close()
    print("落库完成（%d 个包）：%s" % (len(packs), ", ".join(packs)))
    print("路径：", os.path.abspath(m_root))
    return packs


def main():
    p = argparse.ArgumentParser(description="结构化 dossier → 按铁律落 3 包")
    p.add_argument("--id", required=True, help="角色注册 id（如 veronica / luzhao）")
    p.add_argument("--source", required=True, help="结构化 dossier markdown 路径")
    p.add_argument("--name", help="显示名（默认从数据卡取 本名/姓名）")
    p.add_argument("--root", help="记忆根目录（默认 memory/原创角色/<id>）")
    a = p.parse_args()
    build(a.source, a.id, name=a.name, root=a.root)


if __name__ == "__main__":
    main()
