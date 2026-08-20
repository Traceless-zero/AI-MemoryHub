# -*- coding: utf-8 -*-
"""AIMH front-matter 模板 + 写前校验门禁 + 确定性写入。

对应诉求「AI 只能在代码里的模板填写，校验通过才由代码把 front-matter 写入 markdown」：

- ``FM_TEMPLATE`` ：11 字段 + 类型的**唯一真相源**，定义在代码里，不让 AI 手敲 YAML。
- ``validate_fm(d)`` ：结构 + 语义规则，返回 error 列表；空列表=通过。
- ``render_fm(d, body)`` ：校验通过后，借引擎 ``EventPackage`` 确定性写回 ``.md``（正文不丢）。

AI 只负责产出 dict ``d``，不过手 YAML 语法。校验不过 → 拒绝写入（fail-closed）。

注意：模板只管**结构**（字段名/类型），治不了**语义**——真正的价值在 ``validate_fm``
的语义规则层（变体须为同义词、禁跨包污染……）。这些规则正是把「OC 实体塞进变体」
这类坑挡在写前门禁里，而不是等 lint 事后抓。
"""
import os
import sys
import json
import re
import argparse

# 允许脚本直接 `python hma/fm_schema.py` 运行
_here = os.path.dirname(os.path.abspath(__file__))
_repo = os.path.dirname(_here)
if _repo not in sys.path:
    sys.path.insert(0, _repo)

from hma.hma_core import EventPackage  # noqa: E402

# ---------------------------------------------------------------------------
# 1. 模板（唯一真相源）
# ---------------------------------------------------------------------------
REQUIRED = [
    "title", "summary", "tags", "linked", "anchors",
    "person", "event_date", "location", "topic",
    "pkage_created", "pkage_updated",
]

# 字段类型契约：
#   scalar -> str；list -> list；four -> list[dict]（四要素首级 [ ] 形态 [{canon:[variants]}]）
FIELD_TYPES = {
    "title": "scalar", "summary": "scalar",
    "tags": "list", "linked": "list", "anchors": "list",
    "person": "four", "location": "four", "topic": "four",
    "event_date": "scalar", "pkage_created": "scalar", "pkage_updated": "scalar",
}
FORBIDDEN = {"id", "aliases", "features", "created", "updated"}

# 叙事通道（故事书）5 维 keywords 契约（用户 2026-08-13 拍板）：每锚点 keywords 至少覆盖各 ≥1 token
KW_DIMS = ["时间", "地点", "关键事件", "锚定物品", "人物"]

# 概念通道（学术书）5 维 keywords 契约（用户 2026-08-18 拍板）：技术/论证类文章走这套，
# 不逼它填叙事实体维。每锚点 keywords 至少覆盖各 ≥1 token（严格，无适用维豁免）。
CONCEPT_DIMS = ["核心概念", "相关论证", "关键结论", "前置依赖", "反例或争议"]
# 概念维（论证/结论/依赖/争议）无确定性分类源 → 不在 _kw_covered_concept 强制，仅 check_kw_warn 建议。

# 变体疑似具体命名实体（非主题同义词）的廉价启发式
_SUSPECT_VARIANT_CHARS = [
    ("·", "CJK 人名分隔符，疑似具体命名实体"),
    (":", "冒号，疑似复合命名而非同义词"),
]

# 跨包污染门限（与引擎 _GROUND_PKG_GATE 同值）：跨 ≥3 包出现的词算跨包常见词
_PKG_FREQ_GATE = 3

# ---------------------------------------------------------------------------
# 2b. keywords 双通道完整性契约（硬过滤 + 通道内 WARN）
# ---------------------------------------------------------------------------
# 分类只靠**确定性来源**（四要素精确名宇宙 + 年份正则），不靠子串词袋猜分类：
#   - 时间：年份/日期形态（_YEAR_RE）或 包级 event_date≠"—"（pkg_time_ok）
#   - 地点：keyword ∈ 包 location 四要素名宇宙（精确）
#   - 人物：keyword ∈ 包 person 四要素名宇宙（精确）或 含 CJK 人名分隔符 ·
#   - 锚定物品：keyword ∈ 包 topic 四要素名宇宙（精确）或 残余兜底
#   - 核心概念（概念通道）：残余兜底（任何 token 即核心概念）
# 无确定性源的维（关键事件 / 概念4维:论证·结论·依赖·争议）不进强制契约，仅作
# check_kw_warn 建议——它们问的是「作者写这词时想表达什么角色」，无法 deterministic
# 验，硬验只能靠猜（脆性子串袋）。通道归属由包级类型 pkg_narrative 决定，非「哪份契约满足」。
_YEAR_RE = re.compile(r"^\d{4}([-\u2010]\d{2}-\d{2})?$|^\d{4}-\d{4}$")


def _kw_covered_narrative(keywords, pkg_person_names, pkg_loc_names, pkg_topic_names, pkg_time_ok, applicable):
    """返回该锚点 keywords 实际覆盖到的（适用）叙事维集合。

    只用确定性来源，零子串词袋：
      - 时间：年份正则 或 包级 pkg_time_ok（event_date≠"—"）
      - 地点：keyword ∈ 包 location 名宇宙（精确）
      - 人物：keyword ∈ 包 person 名宇宙（精确）或 含 ·
      - 锚定物品：keyword ∈ 包 topic 名宇宙（精确）或 残余兜底
    关键事件 无确定性源 → 永不归入（交给 check_kw_warn 作建议 WARN）。
    """
    covered = set()
    has_residual = False
    for raw in keywords:
        k = str(raw).strip()
        if not k:
            continue
        is_time = bool(_YEAR_RE.match(k))
        is_loc = (k in pkg_loc_names)
        is_person = (k in pkg_person_names) or ("·" in k)
        is_item = (k in pkg_topic_names)
        if is_time:
            covered.add("时间")
        if is_loc and "地点" in applicable:
            covered.add("地点")
        if is_person and "人物" in applicable:
            covered.add("人物")
        if is_item:
            covered.add("锚定物品")
        # 未归入 时间/地点/人物/锚定物品 的 token → 残余（锚定物品兜底）
        if not (is_time or (is_loc and "地点" in applicable)
                or (is_person and "人物" in applicable) or is_item):
            has_residual = True
    if pkg_time_ok:
        covered.add("时间")
    if has_residual:
        covered.add("锚定物品")
    return covered


def check_kw5(d):
    """叙事通道 keywords 契约：每锚点 keywords 须覆盖【适用】叙事维各 ≥1 token。

    强制维 = 时间/地点/人物（包级有则适用，确定性源）+ 锚定物品（残余兜底）。
    关键事件 无确定性源 → 已移出强制契约（见 check_kw_warn 建议 WARN）。
    返回 ERROR 字符串列表（适用维缺任一即报错）。供 validate_fm 与 lint 共用。
    """
    errs = []
    anchors = d.get("anchors")
    if not isinstance(anchors, list):
        return errs
    pkg_person, pkg_loc, pkg_topic = _pkg_name_sets(d, ("person", "location", "topic"))
    pkg_time_ok = bool(d.get("event_date")) and str(d.get("event_date")).strip() not in ("", "—")
    applicable = {"锚定物品"}
    if pkg_time_ok:
        applicable.add("时间")
    if pkg_loc:
        applicable.add("地点")
    if pkg_person:
        applicable.add("人物")
    for i, a in enumerate(anchors):
        if not isinstance(a, dict):
            errs.append("ERROR anchors[%d] 须为 dict（叙事维契约无法校验）" % i)
            continue
        kws = a.get("keywords", a.get("tags"))
        if not isinstance(kws, list):
            errs.append("ERROR anchors[%d].keywords 须为 list（叙事维完整性契约）" % i)
            continue
        covered = _kw_covered_narrative(kws, pkg_person, pkg_loc, pkg_topic, pkg_time_ok, applicable)
        missing = [dim for dim in applicable if dim not in covered]
        if missing:
            errs.append("ERROR anchors[%d].keywords 缺适用叙事维 %s（确定性源：人物/地点四要素+event_date+残余锚定物品）"
                        % (i, "/".join(missing)))
    return errs


def _kw_covered_concept(keywords):
    """概念通道分类：核心概念 靠残余兜底（任何 token 即核心概念）。

    论证/结论/依赖/争议 无确定性源 → 不归入（交给 check_kw_warn 作建议 WARN）。
    """
    has_residual = any(str(raw).strip() for raw in keywords)
    return {"核心概念"} if has_residual else set()


def _pkg_name_sets(d, fields):
    """取四要素字段的精确名宇宙（规范名+变体），确定性分类来源。"""
    sinks = {f: set() for f in fields}
    for f in fields:
        for item in (d.get(f) or []):
            if isinstance(item, dict):
                for canon, variants in item.items():
                    sinks[f].add(str(canon))
                    for v in (variants or []):
                        sinks[f].add(str(v))
    return tuple(sinks[f] for f in fields)


def check_kw(d):
    """双通道 keywords 契约总入口（供 validate_fm / lint 共用）。

    ArrayList 双轨语义（用户 2026-08-18 确认，无显性 type 字段）：
      list1 = 故事书叙事维（时间/地点/人物 按包适用 + 锚定物品，确定性源）
      list2 = 学术书概念维（核心概念，残余兜底）
    通道归属由包级类型决定（pkg_narrative），强制维填满即通过；
    关键事件 / 概念4维 无确定性源 → 不进强制契约（见 check_kw_warn）。
    返回 ERROR 字符串列表（阻断写入）；WARN 见 check_kw_warn（不阻断）。
    """
    errs = []
    anchors = d.get("anchors")
    if not isinstance(anchors, list):
        return errs
    pkg_person, pkg_loc, pkg_topic = _pkg_name_sets(d, ("person", "location", "topic"))
    pkg_time_ok = bool(d.get("event_date")) and str(d.get("event_date")).strip() not in ("", "—")
    pkg_narrative = bool(pkg_person) or bool(pkg_loc) or pkg_time_ok
    applicable = {"锚定物品"}
    if pkg_time_ok:
        applicable.add("时间")
    if pkg_loc:
        applicable.add("地点")
    if pkg_person:
        applicable.add("人物")
    for i, a in enumerate(anchors):
        if not isinstance(a, dict):
            errs.append("ERROR anchors[%d] 须为 dict（双通道契约无法校验）" % i)
            continue
        kws = a.get("keywords", a.get("tags"))
        if not isinstance(kws, list):
            errs.append("ERROR anchors[%d].keywords 须为 list（双通道契约）" % i)
            continue
        # 两条 list 各自覆盖情况（瘦身后强制维仅确定性源；关键事件/概念4维已降 WARN）
        cov_nar = _kw_covered_narrative(kws, pkg_person, pkg_loc, pkg_topic, pkg_time_ok, applicable)
        mand_nar = (set(KW_DIMS) - {"关键事件"}) & applicable
        nar_ok = all(dim in cov_nar for dim in mand_nar)
        cov_con = _kw_covered_concept(kws)
        con_ok = "核心概念" in cov_con
        if nar_ok or con_ok:
            continue  # 任一 list 填满即通过（填一个 list 就回填该 list）
        # 两通道都未填满（通常 keywords 为空）→ ERROR
        nar_miss = [dim for dim in mand_nar if dim not in cov_nar]
        con_miss = [dim for dim in (set(CONCEPT_DIMS) - {"核心概念"}) if dim not in cov_con]
        errs.append(
            "ERROR anchors[%d].keywords 未填满任一通道：叙事缺 %s；概念缺 %s"
            % (i, "/".join(nar_miss) or "（已填满）", "/".join(con_miss) or "（已填满）")
        )
    return errs


def check_kw_warn(d):
    """双通道关键词契约的**建议** WARN（不阻断写入）。

    通道归属由包级类型 _pkg_channel 决定，只报「该包所属通道」的相关 WARN，
    另一通道的 WARN 直接不发（用户 2026-08-18：那个 list 被满足才报它的 WARN）：
      - 叙事包：建议补充 关键事件 维（无确定性分类源，作者意图维）
      - 概念包：建议补充 概念4维（论证/结论/依赖/争议）
    """
    warns = []
    anchors = d.get("anchors")
    if not isinstance(anchors, list):
        return warns
    pkg_person, pkg_loc, pkg_topic = _pkg_name_sets(d, ("person", "location", "topic"))
    pkg_time_ok = bool(d.get("event_date")) and str(d.get("event_date")).strip() not in ("", "—")
    pkg_narrative = bool(pkg_person) or bool(pkg_loc) or pkg_time_ok
    applicable = {"锚定物品"}
    if pkg_time_ok:
        applicable.add("时间")
    if pkg_loc:
        applicable.add("地点")
    if pkg_person:
        applicable.add("人物")
    con4 = set(CONCEPT_DIMS) - {"核心概念"}
    for i, a in enumerate(anchors):
        if not isinstance(a, dict):
            continue
        kws = a.get("keywords", a.get("tags"))
        if not isinstance(kws, list):
            continue
        if pkg_narrative:
            cov = _kw_covered_narrative(kws, pkg_person, pkg_loc, pkg_topic, pkg_time_ok, applicable)
            if "关键事件" not in cov:
                warns.append("WARN anchors[%d] 关键事件 维未显式标注（无确定性源，仅建议补充）" % i)
        else:
            cov_con = _kw_covered_concept(kws)
            miss = [dim for dim in con4 if dim not in cov_con]
            if miss:
                warns.append("WARN anchors[%d] 概念4维未标注 %s（无确定性源，仅建议补充）" % (i, "/".join(miss)))
    return warns


# ---------------------------------------------------------------------------
# 2. 包频表（支撑语义规则「变体禁跨包污染」）
# ---------------------------------------------------------------------------
def build_pkg_docs(memory_root):
    """构建包级文本列表（与引擎 _build_idf 同口径）：每包全部锚点
    title+about+body+keywords 拼合为小写文本，一项=一个包。

    返回 list[str]；无 index.db 时返回空表（语义规则降级为仅廉价启发式）。
    """
    db = os.path.join(memory_root, "index.db")
    if not os.path.isfile(db):
        return []
    try:
        import sqlite3
        con = sqlite3.connect(db)
        docs = []
        for (aj,) in con.execute("SELECT anchors FROM events"):
            try:
                anchors = json.loads(aj or "[]")
            except Exception:
                anchors = []
            parts = []
            for a in anchors:
                if not isinstance(a, dict):
                    continue
                parts.append(a.get("title") or a.get("Chapter") or "")
                parts.append(a.get("about") or a.get("summary") or "")
                parts.append(a.get("body") or "")
                for tg in (a.get("tags") or a.get("keywords") or []):
                    parts.append(tg)
            docs.append(" ".join(parts).lower())
        con.close()
        return docs
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 3. 校验
# ---------------------------------------------------------------------------
def validate_fm(d, memory_root=None):
    """结构 + 语义校验。返回 error 字符串列表；空=通过。

    ``memory_root`` 提供时启用「跨包污染」语义规则（需 index.db）。
    """
    errs = []
    if not isinstance(d, dict):
        return ["ERROR front-matter 必须是 dict"]

    # ① 必填字段齐备
    for r in REQUIRED:
        if r not in d:
            errs.append("ERROR 缺必填字段: %s" % r)

    # ② 禁写字段不得出现
    for f in FORBIDDEN:
        if f in d:
            errs.append("ERROR 禁写字段 %s" % f)

    # ③ 类型契约
    for f, kind in FIELD_TYPES.items():
        if f not in d:
            continue
        v = d[f]
        if kind == "list":
            if not isinstance(v, list):
                errs.append("ERROR %s 须为 list" % f)
        elif kind == "scalar":
            if not isinstance(v, str):
                errs.append("ERROR %s 须为 str" % f)
        elif kind == "four":
            ok = isinstance(v, list) and all(
                isinstance(it, dict) and all(isinstance(k, str) for k in it)
                and all(isinstance(x, list) for x in it.values())
                for it in v
            )
            if not ok:
                errs.append("ERROR %s 须为 list[dict]，每项 {规范名:[变体list]}" % f)

    # ④ 四要素变体语义规则（命名实体 / 跨包污染）
    pkg_docs = build_pkg_docs(memory_root) if memory_root else None
    for f in ("person", "location", "topic"):
        if f not in d or not isinstance(d[f], list):
            continue
        for item in d[f]:
            if not isinstance(item, dict):
                continue
            for canon, variants in item.items():
                for variant in (variants or []):
                    msg = _variant_suspect(str(canon), str(variant), pkg_docs)
                    if msg:
                        errs.append(msg)

    # ⑤ 锚点 keywords 双通道完整性契约（硬过滤：叙事5维 / 概念5维 各缺一则 ERROR，阻断写入）
    errs.extend(check_kw(d))

    return errs


def _variant_suspect(canon, variant, pkg_docs):
    """返回 error 字符串或 None。"""
    v = (variant or "").strip()
    if not v:
        return None
    # 廉价启发式：命名实体分隔符
    for ch, why in _SUSPECT_VARIANT_CHARS:
        if ch in v:
            return "ERROR 变体 %r（规范名 %r）含%s" % (v, canon, why)
    # 跨包污染：变体非规范名子串同义词，且跨 ≥gate 包出现 → 疑似命名实体/泛词
    # 注：单字变体（我/你/他 等代词或极泛称）豁免——它们是合法同义词而非命名实体。
    if pkg_docs is not None:
        vl = v.lower()
        if vl and len(vl) > 1 and vl not in canon.lower():
            cnt = sum(1 for d in pkg_docs if vl in d)
            if cnt >= _PKG_FREQ_GATE:
                return ("ERROR 变体 %r（规范名 %r）跨 %d 包出现，疑似命名实体/泛词而非同义词"
                        % (v, canon, cnt))
    return None


# ---------------------------------------------------------------------------
# 4. 确定性写入（校验通过才落盘）
# ---------------------------------------------------------------------------
def render_fm(d, body, filepath=None):
    """校验通过后确定性写回。返回 (ok, md_text_or_None, errors)。

    AI 只填 dict ``d``；本函数借引擎 EventPackage 序列化（front-matter + 正文，
    正文不丢），等价于「代码把 front-matter 加入 markdown」。
    """
    errs = validate_fm(d)
    if errs:
        return False, None, errs
    pkg = EventPackage(
        title=d.get("title", ""),
        summary=d.get("summary", ""),
        tags=d.get("tags", []),
        linked=d.get("linked", []),
        person=d.get("person", []),
        location=d.get("location", []),
        topic=d.get("topic", []),
        event_date=d.get("event_date", ""),
        anchors=d.get("anchors", []),
        created=d.get("pkage_created", ""),
        updated=d.get("pkage_updated", ""),
        body=body or "",
        path=filepath,
    )
    return True, pkg.to_markdown(), []


# ---------------------------------------------------------------------------
# 5. CLI（演示「AI 填 dict → 校验 → 写入」闭环）
# ---------------------------------------------------------------------------
def _demo():
    root = os.path.join(_repo, "memory")
    print("=== 演示：写前校验门禁 ===\n")

    # 坏例子：复现我们刚修的 OC 实体塞进变体 bug
    bad = {
        "title": "用户数据", "summary": "x", "tags": ["用户"],
        "linked": [], "anchors": [],
        "person": [{"用户": ["我", "用户本人"]}],
        "event_date": "—", "location": [],
        "topic": [{"产出作品": ["HMA", "AIMH", "维罗妮卡", "原创角色",
                                "漫威MCU", "设计", "哲学笔记", "哲学随笔"]}],
        "pkage_created": "2026-07-26", "pkage_updated": "2026-08-13",
    }
    print("[坏例子] topic 变体混入 OC 实体 / 项目码 / 泛词：")
    for e in validate_fm(bad, memory_root=root):
        print("   ", e)
    print("   → 校验未通过，render_fm 拒绝写入\n")

    # 好例子：变体改为真同义词
    good = dict(bad)
    good["topic"] = [{"产出作品": ["作品", "产出物", "成果", "产出"]}]
    print("[好例子] 变体改为真同义词（作品/产出物/成果/产出）：")
    for e in validate_fm(good, memory_root=root):
        print("   ", e)
    ok, md, errs = render_fm(good, "# 用户数据\n\n正文不动。\n", filepath="<demo>")
    print("   → 校验通过=%s，写入字节数=%d\n" % (ok, len(md) if md else 0))

    if ok:
        # 回读证明 round-trip 干净
        pkg = EventPackage.from_markdown(md, filepath="<demo>")
        print("[回读验证] topic 写回为：", pkg.topic)
        print("[回读验证] 正文首行：", repr(pkg.body.splitlines()[0] if pkg.body else ""))

    # 第三例：keywords 5 维完整性硬过滤
    print("\n=== 5 维完整性硬过滤演示 ===\n")
    base_pkg = {
        "title": "示例包", "summary": "x", "tags": ["t"], "linked": [],
        "anchors": [],
        "person": [{"维罗妮卡·夏·雪莱": ["午夜魅影"]}],
        "event_date": "1969-2012", "location": [{"曼哈顿": []}],
        "topic": [], "pkage_created": "2026-08-18", "pkage_updated": "2026-08-18",
    }
    full = dict(base_pkg)
    full["anchors"] = [{"Chapter": "1. 圣保罗之焰", "about": "x",
                        "keywords": ["2005", "曼哈顿", "圣保罗之焰", "宝石", "维罗妮卡·夏·雪莱"]}]
    miss = dict(base_pkg)
    miss["anchors"] = [{"Chapter": "1. 缺维章", "about": "x",
                        "keywords": ["圣保罗之焰", "宝石"]}]  # 缺 时间/地点/人物

    print("[全 5 维] keywords = 时间+地点+关键事件+锚定物品+人物：")
    for e in check_kw5(full):
        print("   ", e)
    print("   → %s\n" % ("通过" if not check_kw5(full) else "未通过"))

    print("[缺 3 维] keywords 仅 关键事件+锚定物品（缺 时间/地点/人物）：")
    for e in check_kw5(miss):
        print("   ", e)
    print("   → %s" % ("通过" if not check_kw5(miss) else "未通过（被硬过滤拦截）"))

    # 第四例：概念通道（学术书）——无叙事信号的纯技术文档走概念5维
    print("\n=== 概念通道（学术书）双轨演示 ===\n")
    concept_pkg = {
        "title": "CEMA 设计原理论文", "summary": "x", "tags": ["t"], "linked": [],
        "anchors": [],
        "person": [], "event_date": "—", "location": [],
        "topic": [], "pkage_created": "2026-08-18", "pkage_updated": "2026-08-18",
    }
    cfull = dict(concept_pkg)
    cfull["anchors"] = [{"Chapter": "2. 锚点模型", "about": "x",
                         "keywords": ["锚点模型", "推导出锚点即索引",
                                      "因此锚点即索引", "依赖 CEMA 循环", "反例：扁平标签"]}]
    cmiss = dict(concept_pkg)
    cmiss["anchors"] = [{"Chapter": "2. 缺维章", "about": "x",
                         "keywords": ["锚点模型", "依托 CEMA 循环"]}]  # 仅 核心概念+前置依赖，缺 相关论证/关键结论/反例或争议

    print("[概念全维] keywords = 核心概念+论证/结论/依赖/争议：")
    for e in check_kw(cfull):
        print("   ", e)
    print("   → 硬过滤 %s（0 ERROR）" % ("拦截" if check_kw(cfull) else "通过"))
    print("   建议 WARN:", check_kw_warn(cfull) or "（无）")

    print("[概念缺4维] keywords 仅 核心概念+前置依赖（缺 论证/结论/反例或争议）：")
    for e in check_kw(cmiss):
        print("   ", e)
    print("   → 硬过滤 %s（概念4维已降为 WARN，不阻断写入）" % ("拦截" if check_kw(cmiss) else "通过"))
    for w in check_kw_warn(cmiss):
        print("     !", w)


def main():
    ap = argparse.ArgumentParser(description="AIMH front-matter 模板/校验/写入")
    ap.add_argument("--validate", metavar="JSON", help="校验一个 front-matter dict(JSON 文件)")
    ap.add_argument("--render", metavar="JSON", help="校验并写入：dict(JSON)+body→out")
    ap.add_argument("--body", metavar="MD", help="--render 所需正文来源 .md")
    ap.add_argument("--out", metavar="MD", help="--render 输出文件")
    ap.add_argument("--root", metavar="DIR", help="memory 根（启用跨包污染语义规则）")
    ap.add_argument("--demo", action="store_true", help="运行内置演示")
    args = ap.parse_args()

    if args.demo:
        _demo()
        return

    if args.validate:
        d = json.load(open(args.validate, encoding="utf-8"))
        for e in validate_fm(d, memory_root=args.root):
            print(e)
        print("结果：%s" % ("通过" if not any(e.startswith("ERROR") for e in validate_fm(d, memory_root=args.root)) else "未通过"))
        return

    if args.render:
        d = json.load(open(args.render, encoding="utf-8"))
        body = open(args.body, encoding="utf-8").read() if args.body else ""
        ok, md, errs = render_fm(d, body, filepath=args.out)
        if not ok:
            for e in errs:
                print(e)
            print("校验未通过，未写入。")
            sys.exit(1)
        out = args.out or (args.render + ".rendered.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(md)
        print("已写入：%s（%d 字节）" % (out, len(md)))
        return

    ap.print_help()


if __name__ == "__main__":
    main()
