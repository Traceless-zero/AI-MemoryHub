# -*- coding: utf-8 -*-
"""本地记忆仓库聚合控制台后端（B 路线·生产版）。

读 memory/index.db + 调 hma_core.Memory.query_anchors 真引擎检索。
stdlib only（http.server），零额外依赖。绑 127.0.0.1，不暴露局域网。

接口：
  GET /                -> 返回前端 HTML（同目录 目录结构树.html）
  GET /api/tree        -> 整体结构树（命名空间->包->md，含 front-matter 摘要）
  GET /api/search?q=   -> 调 Memory.query_anchors 返回 top 锚点卡片
  GET /api/md?path=    -> 返回某 .md 的正文（用于结构树点开看）

启动：python 网页控制台/tree_server.py [port]  或双击 网页控制台/一键启动.bat
说明：本服务是独立于 MCP 的「人直接开浏览器看/搜」入口，读同一 index.db、
      调同一 hma_core，不冲突。
"""

import os
import sys
import json
import re
import sqlite3
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 项目根 = 本文件上两级（网页控制台 -> 项目根）
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
MEMORY_ROOT = os.path.join(PROJECT_ROOT, "memory")
HTML_PATH = os.path.join(HERE, "目录结构树.html")

# 把项目根加进 sys.path 以便 import hma_core
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from hma.hma_core import Memory  # noqa: E402
# dK 瀑布裁切：锚点原始分相邻分差 > CUTOFF_GAP_FLOOR(75) 处单向截断（用户铁律）。
# 直接套在 query_anchors 原始结果上——锚点级安全，不碰 _rerank 的包级 BM25（后者
# 对锚点级有键不匹配 bug，且默认关）。
from hma.recall_obscure import waterfall_cut  # noqa: E402
from hma.scoring_coeffs import CUTOFF_GAP_FLOOR  # noqa: E402


def build_tree():
    """从 index.db 读 events 表，拼成 命名空间->包->md 的树。"""
    db_path = os.path.join(MEMORY_ROOT, "index.db")
    if not os.path.exists(db_path):
        return {"error": "index.db 不存在，请先 rebuild", "packages": []}
    cx = sqlite3.connect(db_path)
    cx.row_factory = sqlite3.Row
    rows = cx.execute(
        "SELECT package_id, filepath, title, summary, anchors, "
        "person, event_date, location, topic, pkage_created, pkage_updated "
        "FROM events ORDER BY package_id"
    ).fetchall()
    cx.close()

    # 结构：ns -> pkg_id -> md 列表
    ns_map = {}
    for r in rows:
        pkg_id = r["package_id"] or ""
        # 命名空间 = 包路径的第一段
        parts = pkg_id.split("/")
        ns = parts[0] if parts else "(root)"
        fn = os.path.basename(r["filepath"] or "")
        anchors = []
        try:
            anchors = json.loads(r["anchors"]) if r["anchors"] else []
        except Exception:
            anchors = []
        md = {
            "file": fn,
            "path": r["filepath"],
            "title": r["title"] or fn,
            "summary": r["summary"] or "",
            "anchor_count": len(anchors),
            "anchors": [a.get("Chapter", "") for a in anchors if isinstance(a, dict)],
            "person": r["person"] or "",
            "event_date": r["event_date"] or "",
            "pkage_created": r["pkage_created"] or "",
        }
        ns_map.setdefault(ns, {}).setdefault(pkg_id, []).append(md)

    tree = []
    for ns, pkgs in sorted(ns_map.items()):
        pkg_list = []
        for pkg_id, mds in sorted(pkgs.items()):
            pkg_list.append({
                "package_id": pkg_id,
                "title": mds[0]["title"] if mds else pkg_id,
                "mds": mds,
            })
        tree.append({"ns": ns, "packages": pkg_list})
    return {"memory_root": MEMORY_ROOT, "namespaces": tree,
            "package_total": sum(len(p["packages"]) for p in tree),
            "md_total": sum(len(m["mds"]) for p in tree for m in p["packages"])}


def _stem_index():
    """建 stem -> [(完整pkg_id, filepath, anchors)] 映射，供 search 反查 filepath。"""
    db_path = os.path.join(MEMORY_ROOT, "index.db")
    if not os.path.exists(db_path):
        return {}
    cx = sqlite3.connect(db_path)
    cx.row_factory = sqlite3.Row
    rows = cx.execute("SELECT package_id, filepath, anchors FROM events").fetchall()
    cx.close()
    m = {}
    for r in rows:
        stem = os.path.splitext(os.path.basename(r["filepath"] or ""))[0]
        anchors = []
        try:
            anchors = json.loads(r["anchors"]) if r["anchors"] else []
        except Exception:
            anchors = []
        m.setdefault(stem, []).append((r["package_id"], r["filepath"], anchors))
    return m


def _anchors_to_results(raw, q, scope=None, drilled=False, package_id=None):
    """把 query_anchors 的 (stem,title,about,locator,score) 元组映射成前端卡片。"""
    stem_map = _stem_index()  # stem -> [(pkg_id, filepath, anchors)]
    results = []
    for stem, atitle, aabout, _loc, score in raw:
        cand = stem_map.get(stem, [])
        filepath = cand[0][1] if cand else ""
        pkg_id = cand[0][0] if cand else stem
        ns = pkg_id.split("/")[0] if "/" in pkg_id else ""
        results.append({
            "title": atitle,
            "package_id": pkg_id,
            "ns": ns,
            "filepath": filepath,
            "summary": aabout,
            "score": round(float(score), 1),
        })
    return {"stage": "hit", "level": "anchor", "results": results, "q": q,
            "scope": scope, "drilled": drilled, "package_id": package_id}


def _dk_cut(raw):
    """dK 瀑布裁切（铁律·CUTOFF_GAP_FLOOR=75）：锚点原始分相邻分差 > 75 处单向截断。

    raw = query_anchors 返回 [(stem,title,about,locator,score)]，score 即锚点原始分
    （_anchor_score 量级）。先按分降序保序（兼容内部 use_field_weights 不改序），
    再 waterfall_cut 裁掉「与 top 分差 > 75」的长尾——这正是 dK 的设计意图：
    只留与最强命中同簇的锚点，弱命中/噪声落入 gap>75 即被砍。
    """
    if not raw:
        return raw
    ordered = sorted(raw, key=lambda x: (-float(x[4]), x[0], x[1]))
    return waterfall_cut(ordered, CUTOFF_GAP_FLOOR)


# 网页检索两级管线的两个可调常数
def _extract_packages(env):
    """从 resolve_two_layer 的四态信封里抽出 (package_id, score, title) 列表。

    resolve_two_layer 是引擎自带的「包级导航 resolver」（L1 目录聚合 + 覆盖率闸门），
    返回 {stage: zero/dir/file/hit, dirs, files, hit}。本函数把命中包统一成
    (pkg_id, 分, 标题)，供网页包级阶段 union。
    """
    out = []
    st = env.get("stage")
    if st == "dir":
        for d in env.get("dirs", []):
            out.append((d["package_id"], float(d.get("score", 0)),
                        d.get("title") or d["package_id"]))
    elif st == "file":
        fs = env.get("files", [])
        if fs:
            out.append((fs[0]["package_id"],
                        max(float(f.get("score", 0)) for f in fs),
                        fs[0].get("title") or fs[0]["package_id"]))
    elif st == "hit" and env.get("hit"):
        h = env["hit"]
        out.append((h["package_id"], float(h.get("score", 0)),
                    h.get("title") or h["package_id"]))
    return out


def _fallback_single_term(mem, q):
    """整句 AND 收窄无交集包时的一步回退：退回『最具体单子词』的结果（非全并集）。

    选词准则：各子词独立 resolve_two_layer 中 top 分最高者优先；同分则包数最少者
    （最具体）优先。只回退到单个主导子词，不回到『所有子词的并集』，避免 OR 噪声。
    """
    parts = [p.strip() for p in re.split(r"[,，、;；\s]+", q) if p.strip()]
    if len(parts) < 2:
        return None
    stem_map = _stem_index()
    best = None  # (key, term, pkg_score, pkg_title)
    for t in parts:
        ps, pt = {}, {}
        for pid, sc, title in _extract_packages(mem.resolve_two_layer(t)):
            if pid not in ps or sc > ps[pid]:
                ps[pid] = sc
                pt[pid] = title
        if not ps:
            continue
        top = max(ps.values())
        key = (-round(float(top), 2), len(ps))  # 分高优先；同分包少优先
        if best is None or key < best[0]:
            best = (key, t, ps, pt)
    if best is None:
        return None
    _k, term, ps, pt = best
    pkgs = []
    for pid, sc in sorted(ps.items(), key=lambda kv: -kv[1]):
        ns = pid.split("/")[0] if "/" in pid else ""
        filepath = ""
        for _stem, entries in stem_map.items():
            for p2, fp, _a in entries:
                if p2 == pid:
                    filepath = fp
                    break
            if filepath:
                break
        pkgs.append({"package_id": pid, "ns": ns,
                     "title": pt.get(pid) or pid.split("/")[-1],
                     "filepath": filepath, "score": round(float(sc), 1)})
    return {"stage": "hit", "level": "package", "results": pkgs, "q": q,
            "scope": None, "fallback": True, "fallback_term": term}


def search(q, top_k=10, scope=None):
    """网页检索入口：两级管线——先包级、后锚点级（user 2026-08-27：缝已有 resolver）。

    直接复用引擎现成的两级 resolver，不另立判定逻辑：
      - 包级 = hma_core.Memory.resolve_two_layer（L1 目录聚合 + 覆盖率闸门，文件级打分）
      - 锚点级 = hma_core.Memory.query_anchors（章节锚点 BM25）

    流程：
      0) 显式 scope（来自包级卡片下钻）→ 直接锚点级，只在该包内召回。
      1) 否则整句入 resolve_two_layer，引擎内部按 term 覆盖率闸门做 AND 收窄
         （"逐渐缩小查询"：包须命中全部子词才候选，不做分列并行并集）。
         无交集包时一步回退到『最具体单子词』结果（非全并集）。
      2) 命中包唯一 → 自动下钻锚点级（query_anchors(package_id=唯一包)）。
      3) 命中包多包 → 阻塞在包级，返回包卡片，由用户点包再下钻（scope=）。
    注：不下钻时整句才送给 query_anchors；逗号等分隔符会破坏其 search_blob LIKE
    预筛（实测 "a，b"→0、空格版正常），故下钻路径统一用 q_clean（分隔符换空格）。
    """
    if not q or not q.strip():
        return {"stage": "zero", "results": [], "level": "package", "q": q, "scope": scope}
    q_clean = re.sub(r"[,，、;；]+", " ", q).strip()  # 下钻路径用，防逗号破 LIKE 预筛
    # 阶段0：显式 scope 下钻 → 锚点级
    if scope:
        mem = Memory(MEMORY_ROOT)
        try:
            raw = mem.query_anchors(q_clean, top_k=top_k, package_id=scope, scope=None)
        finally:
            mem.close()
        raw = _dk_cut(raw)  # dK 瀑布裁切：锚点级长尾按分差>75 截断
        if not raw:
            return {"stage": "zero", "level": "anchor", "results": [],
                    "q": q, "scope": scope, "drilled": True, "package_id": scope}
        return _anchors_to_results(raw, q, scope=scope, drilled=True, package_id=scope)
    # 阶段1：包级 = 整句入 resolve_two_layer，引擎内部按 term 覆盖率闸门做 AND 收窄
    # （即"逐渐缩小查询"：包须命中全部子词才候选，不做分列并行并集）
    mem = Memory(MEMORY_ROOT)
    try:
        pkg_score, pkg_title = {}, {}
        for pid, sc, title in _extract_packages(mem.resolve_two_layer(q)):
            if pid not in pkg_score or sc > pkg_score[pid]:
                pkg_score[pid] = sc
                pkg_title[pid] = title
        if not pkg_score:
            # 一步回退：整句无交集包，退回最具体单子词（非全并集）
            fb = _fallback_single_term(mem, q)
            if fb:
                return fb
            return {"stage": "zero", "level": "package", "results": [],
                    "q": q, "scope": None}
        if len(pkg_score) == 1:
            # 阶段2：命中包唯一 → 自动下钻锚点级
            (unique_pkg,) = pkg_score.keys()
            uraw = mem.query_anchors(q_clean, top_k=top_k, package_id=unique_pkg, scope=None)
            uraw = _dk_cut(uraw)  # dK 瀑布裁切：锚点级长尾按分差>75 截断
            if not uraw:
                return {"stage": "zero", "level": "anchor", "results": [],
                        "q": q, "scope": None, "package_id": unique_pkg}
            return _anchors_to_results(uraw, q, scope=None, drilled=False,
                                       package_id=unique_pkg)
    finally:
        mem.close()
    # 阶段3：命中包多包 → 阻塞在包级，返回包卡片
    pkgs = []
    stem_map = _stem_index()
    for pkg_id, best in sorted(pkg_score.items(), key=lambda kv: -kv[1]):
        ns = pkg_id.split("/")[0] if "/" in pkg_id else ""
        title = pkg_title.get(pkg_id) or pkg_id.split("/")[-1]
        filepath = ""
        for _stem, entries in stem_map.items():
            for pid, fp, _a in entries:
                if pid == pkg_id:
                    filepath = fp
                    break
            if filepath:
                break
        pkgs.append({"package_id": pkg_id, "ns": ns, "title": title,
                     "filepath": filepath, "score": round(float(best), 1)})
    return {"stage": "hit", "level": "package", "results": pkgs, "q": q, "scope": None}


def read_md(path):
    """返回某 .md 的正文全文（用于结构树点开）。

    支持绝对路径或相对 memory 根的路径；相对路径按 MEMORY_ROOT 归一，
    并阻断目录穿越（..）以防越权读仓库外文件。
    """
    if not path:
        return {"error": "未提供 path"}
    # 相对路径 -> 拼到 MEMORY_ROOT
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(MEMORY_ROOT, path))
    # 防穿越：必须仍在 MEMORY_ROOT 内
    if not (os.path.abspath(path) == os.path.abspath(MEMORY_ROOT) or
            os.path.abspath(path).startswith(os.path.abspath(MEMORY_ROOT) + os.sep)):
        return {"error": "非法路径"}
    if not os.path.isfile(path):
        return {"error": "文件不存在"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {"path": path, "content": f.read()}
    except Exception as e:
        return {"error": str(e)}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        data = payload if isinstance(payload, (bytes, bytearray)) else \
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self):
        try:
            with open(HTML_PATH, "r", encoding="utf-8") as f:
                html = f.read().encode("utf-8")
        except Exception as e:
            html = f"<h1>前端 HTML 缺失: {e}</h1>".encode("utf-8")
        self._send(200, html, "text/html; charset=utf-8")

    def _guess_ct(self, p):
        ext = os.path.splitext(p)[1].lower().lstrip(".")
        return {
            "js": "application/javascript; charset=utf-8",
            "mjs": "application/javascript; charset=utf-8",
            "css": "text/css; charset=utf-8",
            "html": "text/html; charset=utf-8",
            "json": "application/json; charset=utf-8",
            "svg": "image/svg+xml",
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "ico": "image/x-icon",
        }.get(ext, "application/octet-stream")

    def _send_static(self, rel):
        """服务前端配套静态文件（marked.min.js 等），仅限 HERE 目录内，阻断目录穿越。"""
        rel = rel.lstrip("/")
        if not rel or ".." in rel.split("/"):
            self._send(404, {"error": "not found"})
            return
        full = os.path.normpath(os.path.join(HERE, rel))
        if full != HERE and not full.startswith(HERE + os.sep):
            self._send(404, {"error": "not found"})
            return
        if not os.path.isfile(full):
            self._send(404, {"error": "not found"})
            return
        ctype = self._guess_ct(full)
        try:
            with open(full, "rb") as f:
                data = f.read()
        except Exception as e:
            self._send(404, {"error": str(e)})
            return
        self._send(200, data, ctype)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            self._send_html()
        elif path == "/api/tree":
            self._send(200, build_tree())
        elif path == "/api/search":
            q = (qs.get("q", [""])[0] or "").strip()
            try:
                top_k = int(qs.get("top_k", ["10"])[0])
            except Exception:
                top_k = 10
            scope = (qs.get("scope", [""])[0] or "").strip() or None
            env = search(q, top_k=top_k, scope=scope)
            env["q"] = q
            env["scope"] = scope
            self._send(200, env)
        elif path == "/api/md":
            p = qs.get("path", [""])[0] or ""
            self._send(200, read_md(p))
        else:
            # 前端配套静态资源（marked.min.js 等）：仅 HERE 目录内，越界即 404
            self._send_static(path)

    def log_message(self, fmt, *args):
        sys.stderr.write("[tree_server] " + (fmt % args) + "\n")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[tree_server] 监听 http://127.0.0.1:{port}  (Ctrl+C 退出)")
    print(f"[tree_server] memory_root = {MEMORY_ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[tree_server] 关闭")
        server.shutdown()


if __name__ == "__main__":
    main()
