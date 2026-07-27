# -*- coding: utf-8 -*-
"""OC 档案路由判定器（确定性，无 LLM）。

=====================================================================
定位：坐在 OC 长期记忆闭环的「第 0 层」——
      写(split) / 检索(oc_registry) / 读(invoke) 之前。

职责：判断一份「OC 素材」是否已经是一份结构化 dossier，
      从而决定走哪条落库路：

  structured  → 自动路：交给 dossier_build 脚本落库
                 （确定性操作，无需 AI 理解）
  ambiguous   → AI 路：交给 AI 理解、抽取字段、按三层铁律落包

---------------------------------------------------------------------
判定轴（真实轴，不是「清晰 vs 模糊」）：
  「源是否已符合 dossier schema」

  强信号（命中即 structured）：
    · 硬数据卡：markdown 表（| 字段 | 内容 |）且其键列覆盖身份属性；
      或 `字段：值` / `字段: 值` 键值对，键集覆盖 ≥3 个身份属性；
    · 或 YAML front-matter 中身份属性键 ≥3 个。

  中信号（分节标题 ≥2 即 structured）：
    dossier 模板分节类别（人生经历 / 能力装备 / 参与事件 /
    人物关系 / 形象外貌 / 性格信条）作为 `##`/`###` 标题出现，
    命中不同类别数 ≥2。

  阈值（保守，宁漏判不误判）：
    强信号命中            → structured
    中信号类别数 ≥ 2     → structured
    其余（纯散文 / 书摘 / 只有对话 / 零散设定）
                          → ambiguous

设计原则（与 HMA / oc-dossier 一致）：
  · 确定性、无状态：纯文本规则命中，不调 LLM、不依赖权重。
  · 只判断、不写库：本脚本是「判定器」，落库交给 build / AI。
  · 可被 AI 直接触发：route 技能首行即调本脚本拿确定性 verdict。
=====================================================================

运行（独立脚本，无需 hma 环境）：
  python oc_classify.py classify path/to/source.md
  python oc_classify.py route    path/to/source.md
  python oc_classify.py classify --dir path/to/examples
"""

import os
import re
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# 1. 身份属性键（强信号判定用）
# ---------------------------------------------------------------------------
IDENTITY_KEYS = [
    "本名", "姓名", "名字", "真名", "全名", "别名", "代号", "英雄代号",
    "年龄", "出生", "身高", "体重", "性别", "国籍", "民族", "种族",
    "身份", "隶属", "阵营", "组织", "职业", "状态", "初次登场", "饰演者",
    "生日", "血型",
]

def _norm_key(k):
    k = k.strip().strip(":：").strip()
    k = k.replace(" ", "").replace("：", "").replace(":", "")
    if k.startswith("字段"):
        k = k[len("字段"):]
    return k


# ---------------------------------------------------------------------------
# 2. 中信号：dossier 模板分节类别
# ---------------------------------------------------------------------------
SECTION_CATEGORIES = [
    ("人生经历", ["人生经历", "生平", "传记", "经历", "背景故事", "背景", "来历", "身世"]),
    ("能力装备", ["能力装备", "能力", "装备", "技能", "武装", "功法", "异能", "武器"]),
    ("参与事件", ["参与事件", "重大事件", "经历的事件", "战绩", "事迹", "参与的重大事件"]),
    ("人物关系", ["人物关系", "关系", "相关人物", "羁绊", "交际", "人际关系"]),
    ("形象外貌", ["形象", "外貌", "相貌", "外表", "外观"]),
    ("性格信条", ["性格", "信条", "行事准则", "语言调性", "行事风格", "人格", "性情"]),
]

HEADING_RE = re.compile(r'^#{1,6}\s+(.+?)\s*$')


# ---------------------------------------------------------------------------
# 3. 强信号：硬数据卡
# ---------------------------------------------------------------------------
def _count_identity_keys_from_kv(lines):
    hit = set()
    kv_re = re.compile(r'^\s*[-*]?\s*([^\n:：]{1,12})\s*[:：]\s*(.+)$')
    for ln in lines:
        m = kv_re.match(ln)
        if not m:
            continue
        key = _norm_key(m.group(1))
        if not key:
            continue
        for ik in IDENTITY_KEYS:
            if ik == key or ik in key or key in ik:
                hit.add(ik)
                break
    return hit

def _count_identity_keys_from_table(lines):
    hit = set()
    for ln in lines:
        s = ln.strip()
        if re.match(r'^\|.*\|\s*$', s):
            if re.match(r'^\|[\s:|-]+\|\s*$', s):
                continue
            first = s.strip("|").split("|")[0].strip()
            key = _norm_key(first)
            if not key:
                continue
            for ik in IDENTITY_KEYS:
                if ik == key or ik in key or key in ik:
                    hit.add(ik)
                    break
    return hit

def _count_identity_keys_from_frontmatter(text):
    hit = set()
    m = re.match(r'^\s*---\s*\n(.*?)\n\s*---\s*\n', text, re.S)
    if not m:
        return hit
    block = m.group(1)
    for ln in block.splitlines():
        kv = re.match(r'^\s*([A-Za-z_\u4e00-\u9fff]+)\s*[:：]\s*(.+)$', ln)
        if not kv:
            continue
        key = _norm_key(kv.group(1))
        for ik in IDENTITY_KEYS:
            if ik == key or ik in key or key in ik:
                hit.add(ik)
                break
    return hit

def _detect_strong(text, lines):
    kv_hit = _count_identity_keys_from_kv(lines)
    tbl_hit = _count_identity_keys_from_table(lines)
    fm_hit = _count_identity_keys_from_frontmatter(text)
    union = kv_hit | tbl_hit | fm_hit
    strong = len(union) >= 3
    return strong, sorted(union)


# ---------------------------------------------------------------------------
# 4. 中信号：分节类别计数
# ---------------------------------------------------------------------------
def _detect_medium(lines):
    cats_hit = set()
    for ln in lines:
        h = HEADING_RE.match(ln)
        if not h:
            continue
        title = h.group(1)
        if "：" in title or ":" in title:
            continue
        for cat, kws in SECTION_CATEGORIES:
            if any(kw in title for kw in kws):
                cats_hit.add(cat)
                break
    return sorted(cats_hit)


# ---------------------------------------------------------------------------
# 5. 综合判定
# ---------------------------------------------------------------------------
def classify_file(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    lines = text.splitlines()
    strong, id_keys = _detect_strong(text, lines)
    medium_cats = _detect_medium(lines)

    if strong:
        verdict = "structured"
        reason = "强信号：硬数据卡覆盖 ≥3 个身份属性（%s）" % "、".join(id_keys)
    elif len(medium_cats) >= 2:
        verdict = "structured"
        reason = "中信号：dossier 分节标题命中 %d 类（%s）" % (
            len(medium_cats), "、".join(medium_cats))
    else:
        verdict = "ambiguous"
        bits = []
        if id_keys:
            bits.append("身份键仅 %d 个（%s）" % (len(id_keys), "、".join(id_keys)))
        if medium_cats:
            bits.append("分节仅 %d 类（%s）" % (len(medium_cats), "、".join(medium_cats)))
        reason = "缺 dossier 结构：" + ("；".join(bits) if bits else "纯散文/书摘/对话，无硬数据卡与分节")

    return {
        "path": path,
        "verdict": verdict,
        "strong": strong,
        "identity_keys": id_keys,
        "medium_cats": medium_cats,
        "reason": reason,
        "route": "auto" if verdict == "structured" else "ai",
    }


# ---------------------------------------------------------------------------
# 6. CLI
# ---------------------------------------------------------------------------
def _print_one(r):
    print("file      : %s" % r["path"])
    print("verdict   : %s" % r["verdict"])
    print("route     : %s  (%s)" % (
        r["route"], "自动化落库" if r["route"] == "auto" else "交 AI 理解抽取"))
    print("强信号    : %s" % ("命中" if r["strong"] else "未命中"))
    if r["identity_keys"]:
        print("  身份键  : %s" % "、".join(r["identity_keys"]))
    print("中信号    : %d 类 %s" % (len(r["medium_cats"]),
                                     "（%s）" % "、".join(r["medium_cats"]) if r["medium_cats"] else ""))
    print("判定依据  : %s" % r["reason"])
    print("-" * 64)

def cmd_classify(args):
    if args.dir:
        results = []
        for fn in sorted(os.listdir(args.dir)):
            if fn.endswith((".md", ".txt")):
                results.append(classify_file(os.path.join(args.dir, fn)))
        for r in results:
            _print_one(r)
        n_auto = sum(1 for r in results if r["route"] == "auto")
        n_ai = len(results) - n_auto
        print("汇总：%d 份 → 自动路 %d，AI 路 %d" % (len(results), n_auto, n_ai))
    else:
        _print_one(classify_file(args.file))

def cmd_route(args):
    r = classify_file(args.file)
    print("file  : %s" % r["path"])
    print("route : %s" % r["route"])
    print("        → %s" % ("自动化 dossier_build 落库"
                             if r["route"] == "auto" else "AI 理解抽取 → 按三层铁律落包"))
    print("依据  : %s" % r["reason"])

def build_parser():
    p = argparse.ArgumentParser(
        prog="oc_classify",
        description="OC 档案路由判定器：判定 dossier 是否结构化，决定自动路 / AI 路")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify", help="判定单个文件 / 批量目录的 verdict")
    c.add_argument("file", nargs="?", help="待判定文件（.md/.txt）")
    c.add_argument("--dir", help="批量判定目录内所有 .md/.txt")
    c.set_defaults(func=cmd_classify)
    r = sub.add_parser("route", help="只输出该文件应走的路（auto / ai）")
    r.add_argument("file", help="待判定文件")
    r.set_defaults(func=cmd_route)
    return p

def main():
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
