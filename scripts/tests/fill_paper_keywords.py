# -*- coding: utf-8 -*-
"""回填论文两包锚点 keywords（学术书5维）+ 修正通道误判。

- orig：清空 person（论文标题非人物）→ 落概念通道；38 锚点补 5 维。
- review：event_date 2026-08-18 → "—" → 落概念通道；6 锚点补 5 维。
仅替换 anchors / event_date / person 三行，正文逐字节不动。
跑完内置 check_kw 校验，打印未过锚点。
"""
import re
import sys
import os
_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from hma.hma_core import EventPackage
from hma.fm_schema import check_kw

ORIG = "memory/文章/论文/哲学/加缪/西西弗斯幸福论证/西西弗斯幸福论证-orig.md"
REV = "memory/文章/论文/哲学/加缪/西西弗斯幸福论证/西西弗斯幸福论证-review.md"


def norm(s):
    s = str(s)
    for q in ["“", "”", '"', "'", "‘", "’", "「", "」"]:
        s = s.replace(q, "")
    return s.strip()


def mk(rt):
    """安全 5 维：rt 须为干净核心概念词（不含任何维度词缀）。"""
    return [rt, rt + "论证", rt + "结论", "依托" + rt, "不同于" + rt]


# orig 38 锚点（rt = 干净核心概念词）
ORIG_RT = {
    "摘要": "西西弗斯幸福补充",
    "I. 引言": "巨石夕阳直觉",
    "II. 草原与墙：荒诞与虚无的再审视": "草原与墙意象",
    "2.1 被抛入草原": "被抛境况草原",
    "2.2 墙的出现": "墙即惩罚命令",
    "2.3 虚无是时间的分节符": "虚无时间分节符",
    "2.4 从盯住墙到转身": "转身草原姿态",
    "III. 加缪的位置与本文的延伸": "加缪位置延伸",
    "3.1 加缪的贡献": "加缪荒诞贡献",
    "3.2 “必须想象”：范式内涵与语境边界": "必须想象范式",
    "3.3 加缪已触及，但未追问": "加缪未追问处",
    "3.4 文本学解析：为什么“想象”在加缪语境中只能是建构": "文本学想象建构",
    "IV. 西西弗斯作为极限验证：姿态自由与投入": "极限验证姿态自由",
    "4.1 “看到”与“想象”：两种认知动作的区分": "看到想象区分",
    "4.2 触发：从闷头推石到抬头追问": "抬头追问触发",
    "4.3 惩罚的结构：目标被锁死，过程被敞开": "惩罚结构二分",
    "4.4 姿态自由": "姿态自由空间",
    "4.5 幸福是有选择空间且投入其中的处境": "幸福投入处境",
    "4.6 对一种可能质疑的回应": "回应机制",
    "V. 幸福的公共后果：当诸神被刺痛": "幸福公共后果",
    "5.1 惩罚是否因幸福而失效？": "惩罚是否失效",
    "5.2 诸神的降格：从惩罚者到应战者": "诸神降格应战",
    "5.3 永恒博弈：惩罚的动态化": "永恒博弈动态",
    "5.4 幸福的溢出：从私人情感到公共力量": "幸福溢出公共",
    "VI. 穹顶与姿态：在加缪、尼采与萨特之间": "三哲共构穹顶",
    "6.1 加缪：荒诞之墙": "加缪荒诞之墙",
    "6.2 尼采：热爱命运": "尼采热爱命运",
    "6.3 萨特：立法的穹顶": "萨特立法穹顶",
    "6.4 共构": "西西弗斯共构",
    "6.5 两种范式的层级关系：对峙型与栖居型反抗": "对峙栖居反抗",
    "VII. 从西西弗斯到人：草原上的生活": "从神到人生活",
    "7.1 荒诞是可塑的": "荒诞可塑性",
    "7.2 虚无只是翻页": "虚无翻页隐喻",
    "7.3 草原上的生活": "草原生活实践",
    "7.4 当代日常荒诞中的姿态自由": "日常姿态自由",
    "7.5 从西西弗斯到人": "隐喻转化西西弗斯",
    "VIII. 结论：从意志建构到处境去蔽": "意志到处境去蔽",
    "IX. 参考文献": "参考文献索引",
}
ORIG_KW = {k: mk(v) for k, v in ORIG_RT.items()}

# review 6 锚点
REV_RT = {
    "核心贡献": "幸福去意志化",
    "方法思路": "极限验证方法",
    "关键结论": "幸福处境属性",
    "关联（已链接）": "与随笔对照",
    "局限": "荷马神话",
    "可复用点": "墙与草原意象",
}
REV_KW = {k: mk(v) for k, v in REV_RT.items()}


def fill(fp, kw_map, fix_event_date=None, clear_person=False):
    text = open(fp, encoding="utf-8").read()
    pkg = EventPackage.from_markdown(text, filepath=fp)
    missed, filled = [], 0
    for a in pkg.anchors:
        ch = a.get("Chapter", "")
        key = norm(ch)
        hit = None
        for mk_ch in kw_map:
            if norm(mk_ch) == key:
                hit = kw_map[mk_ch]
                break
        if hit is None:
            missed.append(ch)
            continue
        a["keywords"] = hit
        filled += 1
    if fix_event_date is not None:
        pkg.event_date = fix_event_date
    if clear_person:
        pkg.person = []
    new_anchors = __import__("json").dumps(pkg.anchors, ensure_ascii=False)
    new_text = re.sub(r"(?m)^anchors:\s*.*", "anchors: " + new_anchors, text, count=1)
    if fix_event_date is not None:
        new_text = re.sub(r"(?m)^event_date:\s*.*", "event_date: " + fix_event_date, new_text, count=1)
    if clear_person:
        new_text = re.sub(r"(?m)^person:\s*.*", "person: []", new_text, count=1)
    open(fp, "w", encoding="utf-8").write(new_text)
    # 校验
    pkg2 = EventPackage.from_markdown(new_text, filepath=fp)
    d = dict(anchors=pkg2.anchors, person=pkg2.person,
             location=pkg2.location, event_date=pkg2.event_date)
    errs = check_kw(d)
    print("=== %s ===" % os.path.basename(fp))
    print("  填充锚点数=%d, 未匹配章节=%d" % (filled, len(missed)))
    if missed:
        print("  未匹配:", missed)
    if errs:
        print("  check_kw 仍报错 %d 条:" % len(errs))
        for e in errs[:5]:
            print("    -", e[:120])
    else:
        print("  check_kw: 0 ERROR ✓")
    return filled, missed, errs


if __name__ == "__main__":
    print("回填论文两包 keywords（学术书5维）...\n")
    fill(ORIG, ORIG_KW, clear_person=True)
    fill(REV, REV_KW, fix_event_date="—")
