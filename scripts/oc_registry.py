# -*- coding: utf-8 -*-
"""OC 名字 → 记忆包 确定性解析器（无状态，可测试）。

用途：当用户在对话里「叫到某个已落库 OC 的名字 / 代号」时，把这句话
确定性地解析到该角色的「基础包」，从而让 oc-dossier（wake 分支）技能启动扮演。

设计原则（与 HMA / oc-dossier 一致）：
  1. .md 是权威源；本解析器只读取 front-matter，不写任何东西。
  2. 无状态确定性：名字/别名命中即映射，不依赖热度/权重/新鲜度。
  3. 基础包是扮演最小单元（tag 含「基础包」或 id 以 -core/-base 结尾）；
     故事包 / 拓展包按 tag 或 id 后缀惰性识别，供扮演时按需召回。

运行（务必在仓库根目录下，使 hma 包可被 import）：
  python scripts/oc_registry.py find "维罗妮卡你在干嘛"   # 解析命中的 OC（实时扫 memory/，无需快照）
  python scripts/oc_registry.py list                  # 列出所有已登记 OC
"""

import os
import sys
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
# 仓库根：脚本可能直接位于仓库根，或在 scripts/ 子目录（R50+ 收拢）
REPO = os.path.dirname(HERE) if os.path.basename(HERE) == "scripts" else HERE
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    from hma_core import Memory
except Exception:
    from hma.hma_core import Memory


# ---------------------------------------------------------------------------
# 基础包 / 故事包 / 拓展包 的识别规则
# ---------------------------------------------------------------------------
def _is_base(tags, rid):
    return ("基础包" in tags) or rid.endswith("-core") or rid.endswith("-base")


def _classify(tags, rid):
    """返回 'base' | 'story' | 'ext' | 'other'。"""
    if _is_base(tags, rid):
        return "base"
    if ("故事包" in tags) or ("起源" in tags) or ("叙事" in tags) \
       or rid.endswith(("-origin", "-tundra", "-story", "-narrative")):
        return "story"
    if ("拓展包" in tags) or rid.endswith("-ext"):
        return "ext"
    return "other"


# ---------------------------------------------------------------------------
# 发现：扫描 memory/原创角色/<char>/ 下直接含的事件 .md（R50 移除 events/ 后）
# ---------------------------------------------------------------------------
def discover(memory_root):
    """memory_root：包含 原创角色/ 的 memory 目录。
    返回 list[dict]，每个 dict 描述一个已登记角色。"""
    oc_root = os.path.join(memory_root, "原创角色")
    if not os.path.isdir(oc_root):
        return []
    ocs = []
    for char in sorted(os.listdir(oc_root)):
        cdir = os.path.join(oc_root, char)
        # R50：包目录直接含事件 .md 即视为已登记角色
        mds = [fn for fn in os.listdir(cdir)
                if fn.endswith(".md") and not fn.endswith(".tmp")
                and os.path.isfile(os.path.join(cdir, fn))] \
            if os.path.isdir(cdir) else []
        if not mds:
            continue
        try:
            m = Memory(cdir)
        except Exception:
            continue
        rows = m.list_all()  # (id, title, tags, updated)
        base_id = None
        base_pkg = None
        packs = []
        for rid, title, tags, updated in rows:
            # list_all() 返回的 tags/aliases/linked 是 json.dumps 存入索引的字符串，
            # 必须先 json.loads 还原为 list；否则 set(str) 会把整串逐字符拆开，
            # 导致 _classify 的 tag 判断失效（历史 bug：曾把 tags 整串逐字符拆成单字符集）。
            try:
                tagset = set(json.loads(tags) if tags else [])
            except Exception:
                tagset = set()
            try:
                pkg = m.read(rid)
            except Exception:
                pkg = None
            packs.append({
                "id": rid,
                "title": title or (pkg.title if pkg else rid),
                "tags": list(tagset),
                "cls": _classify(tagset, rid),
            })
            if base_id is None and _is_base(tagset, rid):
                base_id = rid
                base_pkg = pkg
        if base_id is None:
            # 退化：取首个 -core/-base
            for p in packs:
                if p["id"].endswith(("-core", "-base")):
                    base_id = p["id"]
                    try:
                        base_pkg = m.read(base_id)
                    except Exception:
                        base_pkg = None
                    break
        if base_id is None:
            continue
        if base_pkg is None:
            try:
                base_pkg = m.read(base_id)
            except Exception:
                base_pkg = None
        ocs.append({
            "name": char,
            "root": os.path.abspath(cdir),
            "base_id": base_id,
            "base_title": base_pkg.title if base_pkg else base_id,
            "base_aliases": list(base_pkg.aliases) if base_pkg else [],
            "packs": packs,
        })
    return ocs


# ---------------------------------------------------------------------------
# 名字 → OC 的确定性解析
# ---------------------------------------------------------------------------
def _match_keys(oc):
    keys = set()
    for a in oc.get("base_aliases", []):
        if a:
            keys.add(a.lower())
    keys.add(oc["name"].lower())
    keys.add(oc["base_title"].lower())
    keys.add(oc["base_id"].lower())
    return keys


def find(text, ocs):
    """在 text 中检测是否出现某个已登记 OC 的名字/别名。
    返回 (oc_dict, matched_key) 或 (None, None)。"""
    tl = (text or "").lower()
    if not tl:
        return None, None
    best, best_key = None, None
    best_len = 0
    for oc in ocs:
        for k in _match_keys(oc):
            if k and k in tl and len(k) > best_len:
                best, best_key, best_len = oc, k, len(k)
    return best, best_key


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cmd_find(args):
    # 实时扫 memory/（权威源即 .md 包），无需任何快照 / 缓存。
    ocs = discover(args.root)
    oc, key = find(args.text, ocs)
    if not oc:
        print("(no OC matched)")
        return
    print(f"matched key : {key}")
    print(f"OC name    : {oc['name']}")
    print(f"base pack  : {oc['base_id']}  —  {oc['base_title']}")
    print(f"root       : {oc['root']}")
    print(f"all packs  : {[p['id'] for p in oc['packs']]}")


def cmd_list(args):
    ocs = discover(args.root)
    if not ocs:
        print("(no OC registered under", args.root, ")")
        return
    for oc in ocs:
        print(f"{oc['name']:12}  base={oc['base_id']:16}  "
              f"aliases={oc['base_aliases']}  packs={[p['id'] for p in oc['packs']]}")


def build_parser():
    p = argparse.ArgumentParser(prog="oc_registry",
                                description="OC 名字 → 记忆包 确定性解析器")
    p.add_argument("--root", default="memory",
                   help="包含 原创角色/ 的 memory 目录（默认 ./memory，运行于 hma/ 下）")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find", help="解析一句话里提到的 OC")
    f.add_argument("text", help="用户原话，例如『维罗妮卡你在干嘛』")
    f.set_defaults(func=cmd_find)
    sub.add_parser("list", help="列出所有已登记 OC").set_defaults(func=cmd_list)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
