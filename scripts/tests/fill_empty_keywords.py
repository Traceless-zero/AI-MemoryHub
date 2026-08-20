# -*- coding: utf-8 -*-
"""全库空 keywords 锚点回填（2026-08-19，8.18 待办①收口）。

背景：check_kw 双通道契约（瘦身版）下，四要素全空的包适用维只剩
『锚定物品』（残余兜底）——**任何 ≥1 个非空 token 即通过**（概念通道
『核心概念』同理）。关键事件/概念4维本就是 WARN 级，不参与 ERROR。

规则（确定性、不编造）：
  1. 时间：about/Chapter 里年份 `\\d{4}`（含 19xx/20xx）；
  2. 地点：包 location 四要素名宇宙命中；
  3. 人物：包 person 四要素名宇宙命中或含 `·`；
  4. 锚定物品/核心概念（残余兜底）：about 里 CJK 长名词（≥2 字、非停用词），
     取前 2 个最长的；
  5. 保底：Chapter 标题清洗后（去 `**`/数字编号/标点）的首个长词。
  任一步命中即停（有 token 即通过双通道），全部落空才用 Chapter 保底。

写回纪律（红线）：构造新 EventPackage 必须带全 11 字段（person/location/topic/
event_date 一个不能漏——`_auto_derive` 漏传四要素清空数据的教训），走
to_markdown() 确定性落盘。幂等：已有 keywords 的锚点不动；重跑安全。

用法：python scripts/tests/fill_empty_keywords.py [--apply]
  --apply  落盘写回；缺省 dry-run 只打印将改动数。
"""
import os
import re
import sys

ROOT = r"E:\BaiduNetdiskDownload\项目\AIMH\memory"

sys.path.insert(0, r"E:\BaiduNetdiskDownload\项目\AIMH")
from hma.hma_core import EventPackage  # noqa: E402

_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_STOP = set("的了是在和与或一个我们你们他们这那有进行为对从把被让给来去说看想"
            "系统 架构 设计 文档 模块 机制 使用 相关 以及 已经 当前 现在 需要 可以 "
            "通过 用于 提供 实现 支持 存在 主要 包括 以下 如下 上述 该 此 这 "
            "不是 没有 不能 必须 是否 什么 如何 为什么 其中 部分 内容 问题 情况 "
            "以及 还是 或者 之后 之前 同时 另外 此外 例如 比如 即 等 中 为 与 和 "
            "的 了 是 在 有 也 都 很 更 最 将 已 会 能 要 让 被 把 对 从 向 于 其 "
            "之 及 并 而 但 或 因 由 以 可 需 应 该 说 看 想 见 来 去 做 用 走 成".split())
_CJK_WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
# 中缀停用词：含这些词的连续串不能当名词（会切成整句）
_INFIX_STOP = ("不是", "没有", "可以", "需要", "通过", "提供", "实现", "支持",
               "主要", "包括", "以下", "如下", "用于", "进行", "以及", "是否",
               "什么", "如何", "为什么", "其中", "部分", "内容", "问题", "情况")


def _clean_chapter(ch):
    s = re.sub(r"[*#`\d\s]", "", ch or "")
    s = re.sub(r"[（(【\[][^）)】\]]*[）)】\]]", "", s)  # 去括号说明
    s = re.sub(r"[:：·\-—.。，,、/\\|]", " ", s)
    return s.strip()


def _split_cjk_terms(about):
    """把连续 CJK 串切成候选名词：以中缀停用词为边界切块，块内取 2-5 字片段。"""
    text = about or ""
    # 以中缀停用词为界切分，避免整句串
    chunks = re.split("|".join(re.escape(w) for w in sorted(_INFIX_STOP, key=len, reverse=True)), text)
    words = []
    for ch in chunks:
        for w in _CJK_WORD_RE.findall(ch):
            if len(w) >= 2 and w not in _STOP and not w.isdigit():
                words.append(w)
    # 长串（>5字）二次切分：滑窗取 3-4 字子串，取最长；短串（≤5字）保留原样
    final = []
    for w in words:
        if len(w) <= 5:
            final.append(w)
        else:
            sub = []
            for L in (4, 3):
                for i in range(len(w) - L + 1):
                    piece = w[i:i + L]
                    if piece not in _STOP:
                        sub.append(piece)
            if sub:
                final.append(max(sub, key=len))
    return final


def _pick_from_about(about, chapter, pkg):
    """从锚点内容确定性提取 ≥1 个 token。"""
    text = (about or "") + " " + (chapter or "")
    # 1. 时间
    m = _YEAR_RE.search(text)
    if m:
        return [m.group(1)]
    # 2. 地点（四要素名宇宙）
    for name in pkg.location:
        if name in text:
            return [name]
    # 3. 人物（四要素名宇宙 / 含 ·）
    for name in pkg.person:
        if name in text:
            return [name]
    # 4. 锚定物品/核心概念：CJK 名词（切块），取最长 2 个
    words = _split_cjk_terms(about or "")
    words.sort(key=len, reverse=True)
    if words:
        return words[:1]
    # 5. 保底：Chapter 标题词
    cleaned = _clean_chapter(chapter)
    if cleaned:
        ws = _split_cjk_terms(cleaned)
        ws.sort(key=len, reverse=True)
        if ws:
            return ws[:1]
    return None


def main():
    apply = "--apply" in sys.argv
    changed_files = 0
    changed_anchors = 0
    failed = []
    for dirpath, _dirs, files in os.walk(ROOT):
        for fn in sorted(files):
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    text = f.read()
                if not text.startswith("---"):
                    continue
                pkg = EventPackage.from_markdown(text, fp)
            except Exception as e:
                failed.append((fp, f"parse: {e}"))
                continue
            dirty = False
            for a in pkg.anchors:
                if a.get("keywords"):
                    continue
                toks = _pick_from_about(a.get("about", ""), a.get("Chapter", ""), pkg)
                if toks is None:
                    failed.append((fp, f"anchor 提取失败: {a.get('Chapter')!r}"))
                    continue
                a["keywords"] = toks
                dirty = True
            if not dirty:
                continue
            changed_anchors += sum(
                1 for a in pkg.anchors if a.get("keywords"))
            if apply:
                # 全字段构造（红线：四要素不能漏）→ to_markdown 写回
                updated = EventPackage(
                    id=pkg.id, title=pkg.title, summary=pkg.summary,
                    tags=pkg.tags, linked=pkg.linked,
                    person=pkg.person, location=pkg.location, topic=pkg.topic,
                    event_date=pkg.event_date,
                    created=pkg.created, updated=pkg.updated,
                    body=pkg.body, anchors=pkg.anchors,
                )
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(updated.to_markdown())
            changed_files += 1
            print(f"{'[写回]' if apply else '[dry] '} {os.path.relpath(fp, ROOT)}")

    print(f"\n{'已写回' if apply else '将写回（dry-run）'} {changed_files} 个文件 / {changed_anchors} 个锚点")
    if failed:
        print("未处理：")
        for fp, why in failed:
            print(f"  {fp}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
