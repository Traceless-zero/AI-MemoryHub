# -*- coding: utf-8 -*-
"""修复 veronica-origin.md 的四要素（描述表达式）硬违规 + 清理 keyword 别名/代号。

问题（用户 2026-08-18 指出）：
- person/location/topic 三个四要素一等字段全为空的 []，实体别名/代号/描述表达式
  被塞进 anchors[].keywords（违反 SCHEMA.md §2.0/§2.7：变体归一四要素、别名/代号
  不进 keyword）。
- 例如「黄蓝色的宝石」「蓝钻」是 圣保罗之焰 的描述表达式，应进 topic 变体 dict；
  「午夜魅影」「RB-7」是 维罗妮卡 的代号，应进 person 变体 dict。

修复：
1. 写四要素：person/location/topic = [{规范名:[变体]}, …]（首级 [ ] 形态）。
2. 清理 keyword：移除别名/代号 token（蓝钻/午夜魅影/RB-7/黑寡妇）。
3. 填实四要素后 人物/地点 维变为适用 → 为空/缺维的锚点补齐 5 维（时间/地点/关键事件/
   锚定物品/人物 各≥1 token），使 lint 通过（之前四要素为空掩盖了这些缺口）。

仅改 front-matter，正文逐字节不动。跑完 check_kw5 + validate_fm 校验。
"""
import re
import sys
import os
import json

_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from hma.hma_core import EventPackage, _four_to_list
from hma import fm_schema as F

FP = "memory/原创角色/维罗妮卡·夏·雪莱/veronica-origin.md"

# ---- 四要素（描述表达式）：[{规范名:[变体]}, …] ------------------------------
PERSON = [
    {"维罗妮卡·夏·雪莱": ["RB-7", "午夜魅影", "自由佣兵"]},
    {"娜塔莎·罗曼诺夫": ["黑寡妇"]},
    {"尼克·弗瑞": ["弗瑞"]},
    {"塞莱丝汀·杜·拉克": []},
    {"霍华德·斯塔克": []},
    {"洛基": []},
]
LOCATION = [
    {"红房": ["苏联", "铸造厂"]},
    {"曼哈顿": ["纽约"]},
    {"布达佩斯": []},
    {"华沙": []},
    {"萨拉热窝": []},
    {"伦敦": []},
    {"马德里": []},
    {"莫斯科": []},
    {"伊斯坦布尔": []},
    {"废弃科学城": []},
]
TOPIC = [
    {"圣保罗之焰": ["黄蓝色的宝石", "蓝钻", "深海蓝橙焰钻石", "那颗钻石"]},
    {"幽影核心": ["外星遗骸", "外星技术碎片"]},
    {"协议X-2": ["X-2", "X合同"]},
    {"回旋镖": ["回旋镖计划"]},
]

# ---- 别名/代号 token（须从 keyword 移除，已进四要素）------------------------
ALIAS_TOKENS = {"RB-7", "午夜魅影", "蓝钻", "黑寡妇"}

# ---- 各锚点最终 keywords（按文件顺序，索引对齐）---------------------------
# 5 维：时间/地点/关键事件/锚定物品/人物 各≥1 token（残余法兜底锚定物品）
FINAL_KW = [
    # 0 第一阶段
    ["红房", "铸造厂", "回旋镖计划", "1969", "1980", "维罗妮卡·夏·雪莱", "工具化", "血清", "替代品"],
    # 1 第二阶段
    ["1991", "苏联解体", "布达佩斯", "华沙", "萨拉热窝", "1994", "良知", "生活", "逃亡种子", "维罗妮卡·夏·雪莱", "觉醒"],
    # 2 一、惯性
    ["1991", "1994", "维罗妮卡·夏·雪莱", "布达佩斯", "行动", "惯性"],
    # 3 二、碎裂
    ["1991", "维罗妮卡·夏·雪莱", "苏联解体", "苏联", "变革", "碎裂"],
    # 4 三、重构
    ["1994", "维罗妮卡·夏·雪莱", "布达佩斯", "觉醒", "生活"],
    # 5 四、时机
    ["2002", "维罗妮卡·夏·雪莱", "布达佩斯", "潜伏", "储备"],
    # 6 第三阶段/幽影核心
    ["幽影核心", "2002", "废弃科学城", "力场封存", "维罗妮卡·夏·雪莱", "第8号成功者", "心脏停跳47秒", "外星遗骸", "核心", "转折"],
    # 7 第四阶段/午夜魅影崛起
    ["2003", "2004", "2005", "光学抹除", "圣保罗之焰", "娜塔莎·罗曼诺夫", "2006", "安全屋", "宝石", "钻石"],
    # 8 一、从零开始
    ["维罗妮卡·夏·雪莱", "布达佩斯", "假身份", "潜伏"],
    # 9 二、规则的建立
    ["2004", "维罗妮卡·夏·雪莱", "名声", "潜伏", "布达佩斯"],
    # 10 三、怪盗之夜
    ["怪盗之夜", "2002", "2003", "2005", "光学抹除", "核心隐身", "圣保罗之焰", "宝石", "钻石", "维罗妮卡·夏·雪莱", "布达佩斯"],
    # 11 四、名字的完成
    ["2006", "维罗妮卡·夏·雪莱", "伦敦", "潜伏", "全名"],
    # 12 五、匿名的善举
    ["2007", "维罗妮卡·夏·雪莱", "善举", "潜伏", "布达佩斯"],
    # 13 六、名声
    ["2008", "维罗妮卡·夏·雪莱", "马德里", "名声", "潜伏"],
    # 14 赎回
    ["2005", "维罗妮卡·夏·雪莱", "伊斯坦布尔", "房产", "潜伏"],
    # 15 第五阶段/协议X-2
    ["协议X-2", "2008", "尼克·弗瑞", "神盾局", "2011", "2012", "曼哈顿", "洛基", "合同", "协议"],
    # 16 一、首次接触
    ["2008", "维罗妮卡·夏·雪莱", "弗瑞", "潜伏", "马德里", "接触"],
    # 17 二、任务
    ["维罗妮卡·夏·雪莱", "任务", "潜伏", "布达佩斯"],
    # 18 三、编号
    ["2011", "维罗妮卡·夏·雪莱", "弗瑞", "编号", "潜伏", "曼哈顿"],
    # 19 四、召唤
    ["2012", "维罗妮卡·夏·雪莱", "曼哈顿", "洛基", "潜伏", "转折", "契约"],
]


def main():
    text = open(FP, encoding="utf-8").read()
    pkg = EventPackage.from_markdown(text, filepath=FP)

    # 1) 锚点 keyword：移除别名/代号，按索引写回最终 5 维
    assert len(pkg.anchors) == len(FINAL_KW), \
        "锚点数 %d != FINAL_KW %d，文件结构已变，停止！" % (len(pkg.anchors), len(FINAL_KW))
    for i, a in enumerate(pkg.anchors):
        cleaned = [k for k in (a.get("keywords") or []) or [] if k not in ALIAS_TOKENS]
        # 仍按 FINAL_KW（权威），不依赖原值
        a["keywords"] = FINAL_KW[i]

    new_anchors = json.dumps(pkg.anchors, ensure_ascii=False)

    # 2) 四要素字段写回（首级 [ ] 形态）
    person_s = json.dumps(PERSON, ensure_ascii=False)
    loc_s = json.dumps(LOCATION, ensure_ascii=False)
    topic_s = json.dumps(TOPIC, ensure_ascii=False)

    text = re.sub(r"(?m)^person:\s*.*", "person: " + person_s, text, count=1)
    text = re.sub(r"(?m)^location:\s*.*", "location: " + loc_s, text, count=1)
    text = re.sub(r"(?m)^topic:\s*.*", "topic: " + topic_s, text, count=1)
    # anchors 整块替换（block 形态 → inline JSON）
    text = re.sub(r"(?sm)^anchors:.*?\npkage_created:",
                  "anchors: " + new_anchors + "\npkage_created:", text, count=1)

    open(FP, "w", encoding="utf-8").write(text)

    # 3) 校验（传入完整 11 字段 + 四要素还原为 list[dict] 形态，避免假阳性）
    pkg2 = EventPackage.from_markdown(text, filepath=FP)
    d = dict(
        title=pkg2.title, summary=pkg2.summary, tags=pkg2.tags, linked=pkg2.linked,
        anchors=pkg2.anchors,
        person=_four_to_list(pkg2.person),
        location=_four_to_list(pkg2.location),
        topic=_four_to_list(pkg2.topic),
        event_date=pkg2.event_date,
        pkage_created=pkg2.created,
        pkage_updated=pkg2.updated,
    )
    kw_errs = F.check_kw5(d)
    val_errs = F.validate_fm(d)
    print("=== veronica-origin 四要素修复 ===")
    print("  锚点 keyword 别名清除：", sorted(ALIAS_TOKENS))
    print("  person 规范实体数 =", len(PERSON), " location =", len(LOCATION), " topic =", len(TOPIC))
    if kw_errs:
        print("  check_kw5 ERROR %d 条：" % len(kw_errs))
        for e in kw_errs:
            print("    -", e)
    else:
        print("  check_kw5: 0 ERROR ✓")
    if val_errs:
        print("  validate_fm ERROR %d 条：" % len(val_errs))
        for e in val_errs[:10]:
            print("    -", e)
    else:
        print("  validate_fm: 0 ERROR ✓")
    return kw_errs, val_errs


if __name__ == "__main__":
    main()
