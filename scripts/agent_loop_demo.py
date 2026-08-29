# -*- coding: utf-8 -*-
"""
AIMH 最小 agent loop 演示（接真实 hma_core.Memory 引擎，零 ML）。

把「三层 + 上游意图分流 + 写回按话题落点」钉成可运行代码：
  L3 运行时    -> run()/run_turn() 的 observe -> think -> act -> observe 循环
  L2 策略      -> triage()/recall()/decide()/extract_topic()/route_save_topic()
                  即「系统提示词」的硬编码版（决策在 AI，执行是确定性路由）
  L1 工具/脚本 -> Memory 召回（确定性 BM25 + 歧义/覆盖率闸门）
               -> memory_append_section（往已有包增补章节）/ new_package（新建包）
               -> daylog_append（事件流，最后兜底）

写回哲学（CEMA，纠正 v3 的"分桶"错误）：
  - 不是按「意图类型」分 daylog/todo/done/notes 四类桶 —— 那是外行做法。
  - 而是按「话题/事件」落点：
      1. 提取话题 -> resolve_two_layer 查这个话题有没有对应包
      2. 命中 -> 在那个 .md 里「增加章节模块 / 修改内容」（memory_append_section）
      3. 未命中 -> 新建 .md 文件写入新内容（new_package，带合法 FM）
      4. 最后 -> daylog_append 记「今天发生了这件事」（叙事型 + linked 指向真包，
         不承载真相；daylog 只装闲话+大事件简介+关联）
  - 这正是用户原话：「什么话题事件就去那个 md 文件里增加章节模块或者修改内容。
    再不然就是新建 md 文件写入新内容。最后才是流水账 daylog」。

CEMA 不变：AI 只决策（落哪个包、哪个节、写什么），落盘只走确定性脚本，AI 绝不写回记忆结构。

用法：
  python scripts/agent_loop_demo.py                       # 默认用真实 memory/
  python scripts/agent_loop_demo.py --memory-root /tmp/x  # 用临时副本，不污染真实仓库
"""
import os
import re
import io
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hma.hma_core import Memory

DEFAULT_MEM = os.path.join(ROOT, "memory")

# 新建包 FM 模板（占位 _TITLE_/_SLUG_/_DATE_/_TODAY_ 用 .replace，避开 .format 吞 {}）
NEWPKG_FM = """---
title: _TITLE_
summary: _TITLE_ 相关记忆（agent 按话题落点收录）
tags: [AIMH, agent-loop, _SLUG_]
linked: []
anchors: []
person: [{"用户": ["我", "用户本人"]}]
event_date: "—"
location: []
topic: [{"_TITLE_": ["_SLUG_", "记忆", "话题"]}]
pkage_created: _DATE_
pkage_updated: _TODAY_
---

# _TITLE_

_SECTION_

_BODY_
"""


class AimhAgent:
    def __init__(self, root=DEFAULT_MEM):
        self.root = root
        self.mem = Memory(root)
        self.history = []

    # ---------------- L2 策略：上游意图分流（进记忆库之前） ----------------
    def triage(self, q):
        q = (q or "").strip()
        web_markers = ["新闻", "最新", "股价", "天气", "实时", "今天发生",
                       "2026年", "搜索", "查一下网", "金牌榜", "汇率", "官网"]
        chat_markers = ["吃啥", "吃什么", "干嘛", "你好", "觉得", "无聊",
                        "笑话", "翻译", "心情", "睡了吗", "陪我"]
        if any(m in q for m in web_markers):
            return "web"
        if any(m in q for m in chat_markers):
            return "chat"
        return "memory"

    # ---------------- L2 策略：召回（仅 MEMORY 分支） ----------------
    def recall(self, user_msg):
        env = self.mem.resolve_two_layer(user_msg, top_k=10)
        anchors = self.mem.query_anchors(user_msg, top_k=5)
        return env, anchors

    # ---------------- L2 策略：决策（护栏，仅 MEMORY 分支内） ----------------
    def decide(self, user_msg, env, anchors):
        stage = env.get("stage")
        if stage == "zero":
            return ("abstain", "记忆库中无此内容，无法作答（拒答护栏，不编造）", None)
        if stage in ("dir", "file"):
            cands = env.get("dirs") if stage == "dir" else env.get("files")
            names = [c.get("package_id") or c.get("title") or "?" for c in (cands or [])]
            return ("clarify", "命中多个候选，请澄清你要哪一个：" + " / ".join(names), cands)
        hits = env.get("results") or []
        if hits:
            top = hits[0]
            rid = top.get("package_id")
            body = self.mem.read_body(rid) or top.get("summary", "")
            return ("return", body, top)
        if anchors:
            rid, title, about, locator, _score = anchors[0]
            return ("return", about or locator, {"package_id": rid, "title": title})
        return ("abstain", "检索到候选但无可读正文", None)

    # ---------------- WEB 分支（桩） ----------------
    def web_search(self, q):
        return ("(联网检索占位) 已识别为 WEB 类问题「%s」——生产环境在此调用"
                "联网检索工具并将结果回灌上下文，再交 understand() 作答。" % q)

    # ---------------- 理解层（占位） ----------------
    def understand(self, user_msg, context):
        if not context:
            return "(通用对话模型作答) 收到：「%s」——无需检索记忆库。" % user_msg
        return "【基于 AIMH 召回记忆】\n" + context[:300]

    # ---------------- L2 策略：提取话题（写回落点用） ----------------
    def extract_topic(self, user_msg):
        """从「要记的话」里抽出话题实体。demo 用启发式；生产由理解层 LLM 抽。
        例：'待办：明天对检索架构设计补齐' -> '检索架构'。"""
        q = (user_msg or "").strip()
        for pre in ["待办：", "完成了：", "记住：", "记一下：", "待办:", "完成了:", "记住:"]:
            if q.startswith(pre):
                q = q[len(pre):]
        m = re.search(r"对(.+?)(设计|的|补齐|[\s，。；])", q)
        if m:
            return m.group(1).strip()
        if "的" in q:
            return q.split("的")[0].strip()
        return q[:6].strip()

    def _section_for(self, user_msg):
        if "待办" in user_msg or "要做" in user_msg:
            return "## 待办/未完成"
        if "完成了" in user_msg or "已交付" in user_msg:
            return "## 已完成"
        return "## 备注/进度"

    def is_save_intent(self, q):
        """只有明确「要记」的轮才走写回；查询/闲聊/联网轮不写回（避免 v3 误把
        查询轮当记录意图的 bug）。demo 用启发式；生产由理解层判定。"""
        markers = ["待办", "完成了", "记住", "记一下", "要做", "已交付", "记个"]
        return any(m in (q or "") for m in markers)

    def _pkg_md_path(self, pkg_id):
        """package_id 可能是扁平 .md 也可能是目录（AIMH 真实包是目录结构）。
        先试 pkg_id.md，再试 pkg_id/ 下首个 .md。"""
        p = os.path.join(self.root, pkg_id + ".md")
        if os.path.exists(p):
            return p
        d = os.path.join(self.root, pkg_id)
        if os.path.isdir(d):
            mds = [f for f in os.listdir(d) if f.endswith(".md")]
            if mds:
                return os.path.join(d, mds[0])
        return p

    # ---------------- L1 写回：往已有包增补章节（确定性，调 memory_append_section） ----------------
    def _append_section(self, pkg_path, section, body):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "memory_append_section",
            os.path.join(ROOT, "scripts", "core", "memory_append_section.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        action, _ = mod.append_section(pkg_path, section, body)
        return action

    # ---------------- L1 写回：新建包（确定性，带合法 FM；已存在则增补不覆盖） ----------------
    def new_package(self, topic, section, body):
        today = date.today().isoformat()
        slug = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]+", "-", topic).strip("-") or "未命名"
        pkg_id = "项目/AIMH/" + slug
        path = os.path.join(self.root, "项目", "AIMH", slug + ".md")
        if os.path.exists(path):
            # 已存在（之前轮新建但索引未刷）-> 增补不覆盖，避免误吞已有内容
            self._append_section(path, section, body)
            return pkg_id, path
        fm = (NEWPKG_FM
              .replace("_TITLE_", topic)
              .replace("_SLUG_", slug)
              .replace("_DATE_", today)
              .replace("_TODAY_", today)
              .replace("_SECTION_", section)
              .replace("_BODY_", body.strip()))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write(fm)
        os.replace(tmp, path)
        return pkg_id, path

    # ---------------- L1 写回：daylog 兜底（复用既有脚本，linked 指向真包） ----------------
    def append_daylog(self, text, linked=""):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "daylog_append",
            os.path.join(ROOT, "scripts", "core", "daylog_append.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        argv = ["--title", "agent 落盘：" + text[:18], "--body", text,
                "--touched", "", "--tags", "agent-loop,demo"]
        if linked:
            argv += ["--linked", linked]
        mod.main(argv)
        return os.path.join(self.root, "日志",
                            "daylog-%s.md" % date.today().isoformat())

    # ---------------- 写回总调度：按话题落点 ----------------
    def route_save_topic(self, user_msg):
        topic = self.extract_topic(user_msg)
        section = self._section_for(user_msg)
        env = self.mem.resolve_two_layer(topic, top_k=3)
        stage = env.get("stage")
        pkg_id = None
        if stage == "hit" and env.get("results"):
            pkg_id = env["results"][0]["package_id"]
        elif stage in ("dir", "file"):
            cands = env.get("dirs") or env.get("files") or []
            pkg_id = (cands[0].get("package_id") or cands[0].get("title")) if cands else None

        if pkg_id:
            # 已有包（index 命中）-> 用 filepath 精确定位该 .md，按话题增补章节（不新建、不覆盖）
            # 注意：resolve_two_layer 的 package_id 是「父目录」（如 项目/AIMH），
            # 真正文件名在 filepath / title 字段，不能用 package_id 当路径。
            top = env["results"][0]
            path = top.get("filepath") or self._pkg_md_path(pkg_id)
            action = self._append_section(path, section, user_msg)
            verb = "增补"
            pkg_disp = top.get("title") or pkg_id
        else:
            # index 未命中：可能之前轮已新建但索引未刷 -> 文件系统兜底查
            slug = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]+", "-", topic).strip("-")
            fb = os.path.join(self.root, "项目", "AIMH", slug + ".md")
            if os.path.exists(fb):
                pkg_id, path = "项目/AIMH/" + slug, fb
                action = self._append_section(path, section, user_msg)
                verb = "增补"
                pkg_disp = "项目/AIMH/" + slug
            else:
                # 未命中且文件不存在 -> 新建 .md 写入新内容
                pkg_id, path = self.new_package(topic, section, user_msg)
                action, verb = "created", "新建"
                pkg_disp = pkg_id
        # 最后 daylog 叙事兜底（不承载真相，linked 指向真包）
        verb_label = "增补" if action in ("appended", "replaced") else "新建"
        self.append_daylog("就「%s」%s了记忆包 %s" % (topic, verb_label, pkg_disp), linked=pkg_disp)
        return {"topic": topic, "pkg": pkg_disp, "action": action, "path": path}

    # ---------------- L3 运行时：单轮 ----------------
    def run_turn(self, user_msg):
        route = self.triage(user_msg)
        if route == "chat":
            decision, answer = "chat", self.understand(user_msg, None)
        elif route == "web":
            decision, answer = "web", self.web_search(user_msg)
        else:
            env, anchors = self.recall(user_msg)
            decision, payload, meta = self.decide(user_msg, env, anchors)
            if decision == "abstain":
                answer = "(拒答) " + payload
            elif decision == "clarify":
                answer = "(反问) " + payload
            else:
                answer = self.understand(user_msg, payload)
        saved = self.route_save_topic(user_msg) if self.is_save_intent(user_msg) else None
        self.history.append({"user": user_msg, "decision": decision,
                             "answer": answer, "saved": saved})
        return decision, answer, saved

    # ---------------- L3 运行时：多轮驱动 ----------------
    def run(self, turns):
        print("=" * 64)
        print("AIMH agent loop 启动（接真实 Memory 引擎，零 ML）")
        print("读取侧 triage(CHAT/MEMORY/WEB) + 写回侧按话题落点(增补/新建/最后daylog)")
        print("=" * 64)
        for i, t in enumerate(turns, 1):
            print("\n--- 第 %d 轮 | user: %s ---" % (i, t))
            decision, answer, saved = self.run_turn(t)
            print("  [route]    " + self._route_of(t))
            print("  [decision] " + decision)
            print("  [answer]   " + answer.replace("\n", "\n             "))
            if saved:
                print("  [saved]    话题=%s -> %s %s：%s"
                      % (saved["topic"], saved["action"], saved["pkg"], saved["path"]))

    def _route_of(self, q):
        return {"chat": "CHAT 闲聊（不查记忆）",
                "web": "WEB 联网（接 web 工具）",
                "memory": "MEMORY 查记忆"}.get(self.triage(q), "?")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory-root", default=DEFAULT_MEM,
                    help="memory 根目录；用临时副本跑可避免污染真实仓库")
    args = ap.parse_args()

    demo_turns = [
        "示例信物",                                       # memory -> hit -> return
        "蓝钻",                                             # memory -> dir -> clarify
        "今天晚饭吃什么",                                   # chat   -> 直接答
        "2026年奥运会金牌榜",                               # web    -> 联网桩
        "待办：明天对检索架构设计补齐 rerank 验证",          # save -> 话题=检索架构 -> 无 -> 新建包 ## 待办
        "记住：写回分仓的设计原则",                         # save -> 话题=写回分仓 -> 无 -> 新建包 ## 备注
        "记住：检索架构的 triage 分流已经落地实现",          # save -> 话题=检索架构 -> 命中 -> 增补 ## 备注
    ]
    agent = AimhAgent(root=args.memory_root)
    agent.run(demo_turns)
    # 闭环验证：rebuild 后按话题写回的包可被同一引擎 query 召回（「查不准了去那里找」）
    print("\n" + "=" * 64)
    print("闭环验证：rebuild 索引 + query 召回写回的包")
    print("=" * 64)
    try:
        agent.mem.rebuild_all()
    except Exception:
        import subprocess
        subprocess.run([sys.executable, "scripts/core/rebuild_index.py", "--no-gui"],
                       cwd=ROOT, check=False)
    for t in ["检索架构", "写回分仓"]:
        env = agent.mem.resolve_two_layer(t, top_k=3)
        hits = [r.get("package_id") for r in env.get("results", [])]
        print("  query('%s') -> stage=%s, 命中=%s" % (t, env.get("stage"), hits))
