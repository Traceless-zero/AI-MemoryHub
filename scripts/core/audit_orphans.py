# -*- coding: utf-8 -*-
"""孤儿代码审计（call-graph / necessity audit）——零依赖、只读。

职责：对仓库内全部 .py 做静态调用图统计，回答「这段代码还有没有人用」：
  - 孤儿候选：定义后全仓零引用（Name/Attribute/字符串分发均无）
  - 仅测试可达：调用者全在 scripts/tests/
  - 声明保留：RETAINED 表登记的注入式/接线预留组件
  - 框架回调：装饰器注册（engine/handlers）与宿主库回调（do_*/log_message）
立场：机械层只出「候选 + 证据」，裁决权在人（红线②⑤）。
已知盲区（输出会提示）：
  1. `if False:` / 注释掉的调用仍被 ast 计入（corpus_hit_rerank 案例）——
     死活要看调用点注释，不能只看本脚本；
  2. 同名函数/方法跨类合并计数 → 偏保守（宁可漏报不误报）；
  3. 动态分发只有字符串常量字面可查。

用法：
  python audit_orphans.py --repo <仓库根>
"""

import argparse
import ast
import os
import sys
from collections import defaultdict

EXCLUDE_DIRS = {".git", "__pycache__", "memory", "to_delete", ".workbuddy",
                ".zcode", "node_modules", "vendor", "ff_workspace", "json"}

# 声明保留表（2026-09-05 首轮裁决固化）：注入式组件与接线预留，不报孤儿。
# 增删条目须在此写明理由（红线⑧：机制演进须声明替代关系）。
RETAINED = {
    "assistant_with_tools":
        "llm_adapter 工具循环接线预留（接入 LLM 工具调用时启用）",
    "parse_tool_calls":
        "llm_adapter 工具循环接线预留（同上）",
    "mark_as_complete":
        "FM 补全语义（AI 显式补全且 keywords 必填），regress_tomarkdown_gate 钉住",
    "dispatch":
        "engine 通用派发入口（registry 注册机制的配套 API）：CLI _cmd_* 与 server.HANDLERS 各自持表分发，函数体暂无调用方（2026-09-09 裁决）",
    "_rare_entities":
        "稀有实体筛选（blob+body 两段打捞）：corpus_hit_rerank 废除后生产暂无消费者，"
        "regress_daylog_append E 段钉住打捞行为，供 Gate1 语料包含性未来扩展复用（2026-09-09 裁决）",
}

# 框架回调：宿主库按名字调用，仓库内无 Name 引用属正常。
FRAMEWORK_NAME_PREFIXES = ("do_",)          # http.server 的 do_GET/do_POST ...
FRAMEWORK_NAMES = {"log_message"}           # BaseHTTPRequestHandler


def is_test(rel):
    return rel.startswith("scripts/tests/")




def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="仓库根")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)

    trees = {}
    n_files = 0
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            n_files += 1
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, repo).replace("\\", "/")
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    trees[rel] = ast.parse(f.read())
            except SyntaxError as e:
                print("[skip] 语法错误 %s: %s" % (rel, e))

    defs = defaultdict(list)       # name -> [(rel, lineno)]
    decorated = set()              # 带装饰器的 def（框架托管：@register/@property 等）
    ref_files = defaultdict(set)   # name -> {引用它的文件 rel}
    for rel, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.decorator_list:
                    decorated.add(node.name)
                if not (node.name.startswith("__") and node.name.endswith("__")):
                    defs[node.name].append((rel, node.lineno))
            # 一等公民引用也计数：set_defaults(func=cmd_x)、{name: _h_x}、@deco
            if isinstance(node, ast.Name):
                ref_files[node.id].add(rel)
            elif isinstance(node, ast.Attribute):
                ref_files[node.attr].add(rel)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                ref_files[node.value].add(rel)

    buckets = defaultdict(list)    # 类别 -> [(name, rel, line, extra)]
    n_prod = 0
    for name in sorted(defs):
        sites = defs[name]
        if all(is_test(rel) for rel, _ in sites):
            continue  # 测试文件自定义的辅助函数不在必要性范围
        if name in RETAINED:
            buckets["声明保留"].append((name, sites[0][0], sites[0][1],
                                        RETAINED[name]))
            continue
        callers = ref_files.get(name, set())
        if not callers:
            # 零引用才看豁免：装饰器持有（@register 等）/宿主回调/孤儿
            if name in decorated:
                buckets["装饰器注册"].append((name, sites[0][0], sites[0][1],
                                              "框架托管：装饰器持有引用"))
            elif name.startswith(FRAMEWORK_NAME_PREFIXES) or name in FRAMEWORK_NAMES:
                buckets["框架回调"].append((name, sites[0][0], sites[0][1], ""))
            else:
                buckets["孤儿候选"].append((name, sites[0][0], sites[0][1], ""))
        elif all(is_test(r) for r in callers):
            buckets["仅测试可达"].append((name, sites[0][0], sites[0][1],
                                          "调用: " + ", ".join(sorted(callers))))
        else:
            n_prod += 1

    print("== 孤儿代码审计 ==")
    print("扫描 .py %d 个；生产侧函数定义 %d 个（测试辅助函数不计）"
          % (n_files, len([n for n in defs
                           if not all(is_test(rel) for rel, _ in defs[n])])))
    for cat in ("孤儿候选", "仅测试可达", "声明保留", "装饰器注册", "框架回调"):
        if buckets.get(cat):
            print("%s=%d" % (cat, len(buckets[cat])), end="  ")
    print("生产在役=%d" % n_prod)
    for cat in ("孤儿候选", "仅测试可达", "声明保留", "装饰器注册", "框架回调"):
        if not buckets.get(cat):
            continue
        print("\n-- %s --" % cat)
        for name, rel, ln, extra in buckets[cat]:
            line = "  %s  ← %s:%d" % (name, rel, ln)
            if extra:
                line += " | " + extra
            print(line)
    print("\n[盲区提示] if False:/注释掉的调用仍计入引用（corpus_hit_rerank 案例）；"
          "同名合并计数偏保守。候选须人工核对调用点注释后裁决（红线②⑤）。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
