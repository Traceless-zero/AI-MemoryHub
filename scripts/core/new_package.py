# -*- coding: utf-8 -*-
"""new_package —— 记忆包骨架生成器 + fail-closed 落库入口。

三步工作流（AI 即理解层）：
  1) --print-dict                          ：打印该类型的 front-matter dict 模板（AI 照着填 JSON）
  2) （无 --fill）生成骨架 .md             ：11 字段齐 + 类型化文本块/章节脚手架，AI 再填正文
  3) --fill fm.json --body-file body.md    ：AI 填好 dict + 正文 → validate_fm 校验（fail-closed，
                                             不过不落盘）→ render_fm 确定性渲染 → 写入 <path>/<id>.md

设计原则：
  · 零 ML 零依赖（仅标准库 + hma 包）；校验渲染复用 hma.fm_schema 的唯一权威实现，不另立规则。
  · 落盘后打印 rebuild 提醒（红线：落 .md 必重建索引）。
  · 默认拒绝覆盖已存在的包（--force 才放行）。
  · 路径软检查：目标须在 memory/ 下；新建目录段含 ASCII 时提醒 R59（新建文件夹一律中文）。
"""
import argparse
import datetime
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from hma.fm_schema import render_fm  # noqa: E402  校验+渲染唯一权威实现
from hma.hma_core import EventPackage  # noqa: E402

TODAY = datetime.date.today().isoformat()

# ---- 类型化文本块：每种包类型的骨架差异都在这里定制 ----
# anchors 骨架沿用各分支规范的标准形态；body 是「填写指引」，AI 生成正文时整段替换。
TYPES = {
    "通用": {
        "anchors": [],
        "body": (
            "# <标题>\n\n"
            "> 填写指引（生成后整段替换为本包正文）：\n"
            "> 1. 正文用 `##` 章节组织，每章一个可召回单元；\n"
            "> 2. front-matter 四要素（person/event_date/location/topic）有内容就填，漏填=漏召回；\n"
            "> 3. 锚点 about 写该章独有的特征化摘要（抽掉章名仍可互换 = 泛化，违规）；\n"
            "> 4. 锚点 keywords 满足 5 维（时间/地点/关键事件/锚定物品/人物 各≥1）；\n"
            "> 5. 别名/代号/描述表达式只进四要素变体 dict，绝不进 keywords（描述表达式用斜杠式）。\n"
        ),
    },
    "对话记录": {
        "person": {"<参与方A>": [], "<参与方B>": []},
        "anchors": [
            {"Chapter": "对话原文",
             "about": "本场逐字讨论的要点（议题/分歧/未决项）",
             "keywords": ["讨论", "议题", "分歧"]},
            {"Chapter": "关键内容",
             "about": "本场最后拍板/确定事项要点",
             "keywords": ["拍板", "决定"]},
        ],
        "body": (
            "# <会议/对话标题>\n\n"
            "> 填写指引（对话记录分支，替换本指引）：\n"
            "> 1. `## 对话原文`：逐字 transcript，每轮 `时间戳 | 对话人：对话内容`；\n"
            "> 2. `## 关键内容`：清水决策层，只放最后拍板/确定的事（`时间戳 | 决定`）；\n"
            "> 3. tags 由关键内容派生（单一真相源，勿当词袋全塞）；\n"
            "> 4. 逐场会议独立成包，绝不在写入时静默覆盖旧决定。\n"
        ),
    },
    "论文orig": {
        "anchors": [],
        "body": (
            "> 填写指引（文章·资料分支 orig 包，替换本指引）：\n"
            "> 1. 源是 PDF → 必走确定性重排管线 `python scripts/core/pdf_reflow.py <pdf> --write memory <包相对路径> <主题>-orig`；\n"
            "> 2. 大文件/敏感/版权内容留仓库外，本包只记一句指向；\n"
            "> 3. 元信息（标题/作者/出处/年份/DOI）写进 body 顶部或 summary；\n"
            "> 4. 锚点按最小单元 derive_anchors(max_level=6) 全层级细切；关键词部分整段一个锚点。\n"
        ),
    },
    "论文review": {
        "anchors": [],
        "body": (
            "# <主题> 理解综述\n\n"
            "> 填写指引（review 包 = 核心交付物，替换本指引）：\n"
            "> 1. 一句话核心贡献；2. 方法思路；3. 关键结论；\n"
            "> 4. 与已有记忆的关联（真相关才 linked，不编 id）；5. 局限；6. 可复用点。\n"
            "> summary 落核心贡献一句话，保证 L1 可召回。绝不把全文重读进上下文。\n"
        ),
    },
    "疾病": {
        "location": {"<解剖位点>": ["<亚位点>"]},
        "anchors": [
            {"Chapter": "定义与病理", "about": "<该病定义与主要病因（特征化）>",
             "keywords": ["<病名>", "<ICD编码>", "<病因>"]},
            {"Chapter": "临床表现与症状", "about": "<症状群（含不典型症状，医学正确性优先，不得为消歧删症状）>",
             "keywords": ["<症状1>", "<症状2>"]},
            {"Chapter": "客观检查与诊断标准", "about": "<高判别力检查/检验与诊断标准（精筛靠它们）>",
             "keywords": ["<检查1>", "<检验1>", "<诊断标准>"]},
            {"Chapter": "治疗与预后", "about": "<治疗线与预后要点>",
             "keywords": ["<治疗1>", "<预后>"]},
        ],
        "body": (
            "# <病名>（<全称>）\n\n"
            "> 填写指引（医学域 一病一包，替换本指引）：\n"
            "> 1. 一病一包；ICD 编码化作锚定物品 keyword（类比法条号）；\n"
            "> 2. 发病位置=解剖位点填 location 四要素；症状进锚点 keywords（斜杠式变体）；\n"
            "> 3. 必须有「客观检查与诊断标准」锚点（分阶段精筛靠 BNP/肌钙蛋白类高判别力实体）；\n"
            "> 4. 医学正确性优先：FM 不得为消歧而删不典型症状；诊断决策交人，LLM 零诊断。\n"
        ),
    },
}


def _type_names():
    return " / ".join(TYPES)


def build_skeleton(ttype, title):
    """生成骨架 .md 文本（dict 占位 + 类型化文本块）。"""
    t = TYPES[ttype]
    d = {
        "title": title,
        "summary": "<2~4 句自包含真概要，落关键事实首行保证 L1 可召回>",
        "tags": ["<标签1>", "<标签2>"],
        "linked": [],
        "person": t.get("person", []),
        "event_date": "—",
        "location": t.get("location", []),
        "topic": [{"<规范主题>": ["<变体1>", "<变体2>"]}] if ttype in ("通用", "疾病") else [],
        "anchors": t.get("anchors", []),
        "pkage_created": TODAY,
        "pkage_updated": TODAY,
    }
    # 借 render_fm 的序列化（此时不含 AI 内容，跳过校验，直接走 EventPackage 渲染会失败，
    # 因此骨架用轻量手拼：字段顺序固定、JSON 单行，引擎 _parse_fm 兼容）。
    def j(v):
        return json.dumps(v, ensure_ascii=False)
    fm = (
        "---\n"
        f"title: {d['title']}\n"
        f"summary: {d['summary']}\n"
        f"tags: {j(d['tags'])}\n"
        f"linked: {j(d['linked'])}\n"
        f"person: {j(d['person'])}\n"
        f"event_date: \"{d['event_date']}\"\n"
        f"location: {j(d['location'])}\n"
        f"topic: {j(d['topic'])}\n"
        f"anchors:\n" + "".join(
            f"  - Chapter: {json.dumps(a['Chapter'], ensure_ascii=False)}\n"
            f"    about: {json.dumps(a['about'], ensure_ascii=False)}\n"
            f"    keywords: {j(a['keywords'])}\n" for a in d["anchors"]) +
        f"pkage_created: {d['pkage_created']}\n"
        f"pkage_updated: {d['pkage_updated']}\n"
        "---\n\n" + t["body"]
    )
    return fm, d


def print_dict_template(ttype):
    t = TYPES[ttype]
    d = {
        "title": "<标题>",
        "summary": "<2~4 句自包含真概要>",
        "tags": ["<标签1>", "<标签2>"],
        "linked": ["<关联包复合id，无则空表>"],
        "person": t.get("person", []),
        "event_date": "—",
        "location": t.get("location", []),
        "topic": [{"<规范主题>": ["<变体1>"]}],
        "anchors": t.get("anchors") or [{"Chapter": "<章名>", "about": "<特征化摘要>",
                                          "keywords": ["<时间维>", "<地点维>", "<关键事件>", "<锚定物品>", "<人物>"]}],
        "pkage_created": TODAY,
        "pkage_updated": TODAY,
    }
    print("// 照此结构填 JSON（保存为文件后用 --fill 传入；校验不过不落盘）")
    print("// 11 字段一个不许省；event_date 无时间写 \"—\"；禁写 id/aliases/features/created/updated")
    print(json.dumps(d, ensure_ascii=False, indent=2))


# ---- 模块集：新建项目时的标准 4 状态模块骨架（口径=aimh-project 技能） ----
# 开发日志.md 永不预建/手写——由 derive_topic_views.py 从 daylog 派生。
MODULE_SETS = {
    "项目": [
        ("需求清单",
         "需求待办", "roadmap",
         "# {proj} 需求清单\n\n## 待办\n\n- [ ] <需求条目一>\n- [ ] <需求条目二>\n\n## 已完成\n\n- [x] <已完成条目>（完成于 YYYY-MM-DD）\n\n> 活待办：每条显式标 已完成/未完成；这是项目的 roadmap，随做随更。\n"),
        ("项目结构",
         "目录布局", "结构总览",
         "# {proj} 项目结构\n\n## 目录布局\n\n```\n<目录树占位：只描述目录与文件布局>\n```\n\n> ⚠️ 本文件只装结构。铁律/约定/架构决策等「死东西」一律进 约定.md / 架构.md，不混入本文件。\n"),
        ("约定",
         "铁律协作", "规矩约定",
         "# {proj} 约定\n\n## 铁律（不可违反）\n\n- <编码铁律 / 红线>\n\n## 协作约定\n\n- <协作方式 / 流程约定>\n\n> 「死东西」单独成文件，与结构、日志解耦。\n"),
        ("架构",
         "系统设计", "模块关系",
         "# {proj} 架构\n\n## 系统是什么\n\n<一句话 + 设计原理>\n\n## 模块间关系\n\n<模块划分与依赖关系；讲「为什么这样」>\n"),
    ],
}


def build_module_set(tset, project, path):
    """生成项目模块集骨架：返回 [(out_path, md_text), ...]。linked 四模块互链。"""
    mods = MODULE_SETS[tset]
    ids = [f"{project}-{name}" for name, _, _, _ in mods]
    out = []
    for (name, kw_event, kw_anchor, body_tpl), mid in zip(mods, ids):
        siblings = [x for x in ids if x != mid]
        d = {
            "title": f"{project} {name}",
            "summary": f"<2~4 句自包含真概要：{project} 的{name}模块，落关键事实首行>",
            "tags": ["project", project, kw_event],
            "linked": siblings,
            "person": [{"用户": ["我"]}],
            "event_date": "—",
            "location": [],
            "topic": [{project: [kw_event, kw_anchor]}],
            "anchors": [{"Chapter": name, "about": f"<{project} {name}章的特征化摘要>",
                          "keywords": [TODAY, f"{project}目录", kw_event, kw_anchor, "用户"]}],
            "pkage_created": TODAY,
            "pkage_updated": TODAY,
        }
        body = body_tpl.replace("{proj}", project)
        def j(v):
            return json.dumps(v, ensure_ascii=False)
        md = (
            "---\n"
            f"title: {d['title']}\n"
            f"summary: {d['summary']}\n"
            f"tags: {j(d['tags'])}\n"
            f"linked: {j(d['linked'])}\n"
            f"person: {j(d['person'])}\n"
            f"event_date: \"{d['event_date']}\"\n"
            f"location: {j(d['location'])}\n"
            f"topic: {j(d['topic'])}\n"
            f"anchors:\n" + "".join(
                f"  - Chapter: {json.dumps(a['Chapter'], ensure_ascii=False)}\n"
                f"    about: {json.dumps(a['about'], ensure_ascii=False)}\n"
                f"    keywords: {j(a['keywords'])}\n" for a in d["anchors"]) +
            f"pkage_created: {d['pkage_created']}\n"
            f"pkage_updated: {d['pkage_updated']}\n"
            "---\n\n" + body
        )
        out.append((os.path.join(path, mid + ".md"), md))
    return out


def _norm_field(v):
    """旧式裸 dict（{规范名:[变体]}）→ 规范 list[dict]；list 原样返回。与引擎读时归一同语义。"""
    if isinstance(v, dict):
        return [{k: (vs or [])} for k, vs in v.items()]
    return v or []


def do_export(target, work_dir):
    """包 → 可编辑工作区：拆出 fm.json + body.md（AI 用编辑工具改，再 --import 回写）。"""
    if not os.path.exists(target):
        print(f"[x] 目标不存在：{target}")
        return 1
    pkg = EventPackage.from_markdown(io.open(target, encoding="utf-8").read(), target)
    stem = pkg.id or os.path.splitext(os.path.basename(target))[0]
    workdir = work_dir or os.path.join(os.environ.get("TEMP", "."), "aimh_edit", stem)
    os.makedirs(workdir, exist_ok=True)
    d = {
        "title": pkg.title,
        "summary": pkg.summary,
        "tags": pkg.tags or [],
        "linked": pkg.linked or [],
        "person": _norm_field(pkg.person),
        "event_date": pkg.event_date,
        "location": _norm_field(pkg.location),
        "topic": _norm_field(pkg.topic),
        "anchors": pkg.anchors or [],
        "pkage_created": pkg.created,
        "pkage_updated": pkg.updated,
    }
    fm_path = os.path.join(workdir, stem + ".fm.json")
    body_path = os.path.join(workdir, stem + ".body.md")
    json.dump(d, io.open(fm_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    io.open(body_path, "w", encoding="utf-8", newline="\n").write(pkg.body or "")
    print(f"[+] 已导出（可编辑工作区）：")
    print(f"    front-matter dict : {fm_path}")
    print(f"    正文 body         : {body_path}")
    print(f"    目标包            : {target}")
    print("    下一步：AI 编辑上述两文件（fm.json 改字段/锚点，body.md 改正文），然后回写：")
    print(f"    python scripts/core/new_package.py --import \"{target}\" --fill \"{fm_path}\" --body-file \"{body_path}\"")
    return 0


def do_import(target, fill, body_file, keep_updated):
    """工作区 → 包：validate_fm fail-closed → render_fm 确定性写回原路径。"""
    if not os.path.exists(target):
        print(f"[x] 目标不存在（--import 只改既有包，新建请走 --fill / 骨架模式）：{target}")
        return 1
    try:
        d = json.load(io.open(fill, encoding="utf-8"))
    except Exception as e:
        print(f"[x] --fill JSON 解析失败：{e}")
        return 1
    body = io.open(body_file, encoding="utf-8").read()
    if not keep_updated:
        d["pkage_updated"] = TODAY          # 编辑即更新（语义：pkage_updated=最后一次修改日）
    ok, md, errs = render_fm(d, body, filepath=target)
    if not ok:
        print("[x] validate_fm 未通过，未落盘（fail-closed）：")
        for e in errs:
            print("   -", e)
        return 1
    io.open(target, "w", encoding="utf-8", newline="\n").write(md)
    print(f"[+] 已写回（validate_fm 通过，render_fm 确定性渲染；pkage_updated={d['pkage_updated']}）：{target}")
    print("[!] 红线：落 .md 必重建索引 → python scripts/core/rebuild_index.py --no-gui")
    print("    建议随即 git diff 复核本次改动。")
    return 0


def path_soft_check(path):
    warns = []
    norm = path.replace("\\", "/").strip("/")
    if not (norm == "memory" or norm.startswith("memory/")):
        warns.append("目标不在 memory/ 下（单存储原则：记忆只进 memory/）")
    segs = [s for s in norm.split("/") if s][1:]  # 去掉 memory 本身
    for s in segs:
        if re.fullmatch(r"[A-Za-z0-9._-]+", s):
            warns.append(f"目录段「{s}」为纯 ASCII —— R59：新建文件夹一律中文（用户明确要求英文除外）")
            break
    return warns


def main(argv=None):
    ap = argparse.ArgumentParser(description="记忆包骨架生成器 + fail-closed 落库入口")
    ap.add_argument("--type", default="通用", help=f"包类型：{_type_names()}")
    ap.add_argument("--path", default="", help="目标目录（如 memory/其他/法律/民法典）")
    ap.add_argument("--id", dest="pid", default="", help="包 id = .md 文件名 stem")
    ap.add_argument("--title", default="", help="包标题（骨架模式必填）")
    ap.add_argument("--print-dict", action="store_true", help="只打印该类型的 dict 模板后退出")
    ap.add_argument("--module-set", default="", help=f"整集生成模块骨架：{' / '.join(MODULE_SETS)}（配合 --path=memory/项目/<项目名> 与 --project）")
    ap.add_argument("--project", default="", help="项目名（--module-set 模式必填，中文）")
    ap.add_argument("--fill", default="", help="AI 填好的 front-matter dict JSON 文件 → 校验+渲染+落盘")
    ap.add_argument("--export", default="", metavar="MD", help="导出既有包为可编辑工作区（fm.json + body.md）")
    ap.add_argument("--import", dest="import_path", default="", metavar="MD", help="把编辑好的 fm.json+body.md 写回该既有包（配合 --fill/--body-file）")
    ap.add_argument("--work-dir", default="", help="--export 的工作目录（默认 %%TEMP%%/aimh_edit/<id>）")
    ap.add_argument("--keep-updated", action="store_true", help="--import 时保留原 pkage_updated（默认自动改为今天）")
    ap.add_argument("--body-file", default="", help="正文 markdown 文件（--fill 模式必填）")
    ap.add_argument("--out", default="", help="输出路径（默认 <path>/<id>.md）")
    ap.add_argument("--force", action="store_true", help="允许覆盖已存在的文件（默认拒绝）")
    a = ap.parse_args(argv)

    if a.print_dict:
        if a.type not in TYPES:
            ap.error(f"--type 须为：{_type_names()}")
        print_dict_template(a.type)
        return 0

    if a.export:
        return do_export(a.export, a.work_dir)
    if a.import_path:
        if not (a.fill and a.body_file):
            ap.error("--import 需 --fill fm.json 与 --body-file body.md")
        return do_import(a.import_path, a.fill, a.body_file, a.keep_updated)

    if a.module_set:
        # 模块集模式：整集生成（已存在的文件跳过，绝不覆盖）
        if a.module_set not in MODULE_SETS:
            ap.error(f"--module-set 须为：{' / '.join(MODULE_SETS)}")
        if not (a.path and a.project):
            ap.error("--module-set 需 --path=memory/项目/<项目名> 与 --project <项目名>")
        for w in path_soft_check(a.path):
            print(f"[warn] {w}")
        created, skipped = [], []
        for out, md in build_module_set(a.module_set, a.project, a.path):
            if os.path.exists(out):
                skipped.append(out)
                continue
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            io.open(out, "w", encoding="utf-8", newline="\n").write(md)
            created.append(out)
        for c in created:
            print(f"[+] 骨架已生成：{c}")
        for s in skipped:
            print(f"[=] 已存在，跳过（绝不覆盖）：{s}")
        print("    查重/增补口径见 aimh-project 技能第 2 步；开发日志.md 不预建（由 derive_topic_views 派生）。")
        print("[!] 红线：落 .md 必重建索引 → python scripts/core/rebuild_index.py --no-gui")
        return 0

    if not (a.path and a.pid):
        ap.error("--path 与 --id 必填（或用 --print-dict 只看模板 / --module-set 整集生成）")
    out = a.out or os.path.join(a.path, a.pid + ".md")

    for w in path_soft_check(a.path):
        print(f"[warn] {w}")

    if os.path.exists(out) and not a.force:
        print(f"[x] 目标已存在（拒绝覆盖，防手滑毁包）：{out}\n    确认要覆盖请加 --force；改归类请走 aimh-relocate。")
        return 1

    if not a.fill:
        # 骨架模式
        if not a.title:
            ap.error("骨架模式需 --title（占位标题）")
        if a.type not in TYPES:
            ap.error(f"--type 须为：{_type_names()}")
        fm, _ = build_skeleton(a.type, a.title)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        io.open(out, "w", encoding="utf-8", newline="\n").write(fm)
        print(f"[+] 骨架已生成：{out}")
        print("    下一步：填好 front-matter 与正文后，二选一收尾——")
        print("      a) 保存 dict 为 JSON → python scripts/core/new_package.py --type {} --path {} --id {} --fill fm.json --body-file body.md（fail-closed 校验）".format(a.type, a.path, a.pid))
        print("      b) 直接编辑 .md → python scripts/core/rebuild_index.py --no-gui")
        return 0

    # --fill 模式：validate + render（fail-closed，复用 fm_schema 唯一权威实现）
    if not a.body_file:
        ap.error("--fill 模式需 --body-file（正文 markdown）")
    try:
        d = json.load(io.open(a.fill, encoding="utf-8"))
    except Exception as e:
        print(f"[x] --fill JSON 解析失败：{e}")
        return 1
    body = io.open(a.body_file, encoding="utf-8").read()
    ok, md, errs = render_fm(d, body, filepath=out)
    if not ok:
        print("[x] validate_fm 未通过，未落盘（fail-closed）：")
        for e in errs:
            print("   -", e)
        return 1
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    io.open(out, "w", encoding="utf-8", newline="\n").write(md)
    print(f"[+] 已落盘（validate_fm 通过，render_fm 确定性渲染）：{out}")
    print("[!] 红线：落 .md 必重建索引 → python scripts/core/rebuild_index.py --no-gui")
    return 0


if __name__ == "__main__":
    sys.exit(main())
