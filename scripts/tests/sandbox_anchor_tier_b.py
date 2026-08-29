# -*- coding: utf-8 -*-
"""沙箱验证：B 方案（锚点 keyword 移出 proper-noun 通道、改走独立档 ≈100/40）。

不修改任何生产文件：用 MemorySandbox(Memory) 子类覆盖 _score / resolve_two_layer，
读真实 index.db 验证。拟落地产物：
  - scoring_coeffs.FIELD_IMP["anchor"] = 0.667
  - PKG_ANCHOR_KW_EXACT  = _tier("anchor", MATCH_EXACT)   = 150*0.667*1.0   ≈ 100.05
  - PKG_ANCHOR_KW_SUBSTR = _tier("anchor", MATCH_CONTAINS)= 150*0.667*0.4   ≈ 40.02
  - resolve_two_layer：锚点 keyword 从 other_aliases 分离到 anchor_kw，Chapter 仍进 other_aliases
  - _score(...) 末位加 anchor_aliases=None 参数，加独立分支

治本思路：让「示例事件」「哲学」这类只活在锚点 keyword 的词，不再蹭 proper-noun EXACT=150，
而是走独立 anchor 档（约 100）。既保住示例事件唯一命中示例角色，又不污染"哲学"包级聚合
（日志/design-journal 锚点 keyword「哲学」只计 100，不会把真正 tag 含「哲学」的随笔/论文挤出 waterfall）。

生产落地需用户显式确认。本脚本只读索引，不碰生产文件、不重启后端。
"""
import sys, os
sys.path.insert(0, r"E:/BaiduNetdiskDownload/项目/AIMH")
import json
from hma.hma_core import Memory, normalize_terms, _is_garbage_bigram, _flat_variants
from hma import scoring_coeffs as C

# ---- 拟落地产物：anchor 独立档 ----
# FIELD_IMP["anchor"] = 0.667（介于 tag 0.6 与 title 0.8 之间，低于 proper-noun 1.0）
ANCHOR_IMP = 0.667
PKG_ANCHOR_KW_EXACT = 150.0 * ANCHOR_IMP * 1.0    # ≈ 100.05
PKG_ANCHOR_KW_SUBSTR = 150.0 * ANCHOR_IMP * 0.4   # ≈ 40.02

print(f"[沙箱 B] 拟落地产物: FIELD_IMP['anchor']={ANCHOR_IMP} "
      f"PKG_ANCHOR_KW_EXACT={PKG_ANCHOR_KW_EXACT:.2f} "
      f"PKG_ANCHOR_KW_SUBSTR={PKG_ANCHOR_KW_SUBSTR:.2f}\n")


class MemorySandbox(Memory):
    @staticmethod
    def _score(ql, rid, title, summary, person_aliases, other_aliases, tags, anchor_aliases=None):
        """复刻生产 _score + 末位加 anchor_aliases 独立档（不蹭 proper-noun EXACT 150）。"""
        terms = normalize_terms(ql)
        if not terms:
            return 0
        rid_l = rid.lower()
        title_l = (title or "").lower()
        sum_l = (summary or "").lower()
        tags_l = [t.lower() for t in tags]
        p_al = [a.lower() for a in person_aliases]
        o_al = [a.lower() for a in other_aliases]
        a_al = [x.lower() for x in (anchor_aliases or [])]

        s = 0
        if ql == rid_l:
            s += C.PKG_ID_EXACT
        elif any(t in rid_l for t in terms):
            s += C.PKG_ID_SUBSTR
        for t in terms:
            best = 0
            # person alias（高杠杆）
            if any(t == al for al in p_al):
                best = max(best, C.PKG_PERSON_ALIAS_EXACT)
            elif any(t in al for al in p_al):
                best = max(best, C.PKG_PERSON_ALIAS_SUBSTR)
            # 其他 alias（topic/location）
            if any(t == al for al in o_al):
                best = max(best, C.PKG_OTHER_ALIAS_EXACT)
            elif any(t in al for al in o_al):
                best = max(best, C.PKG_OTHER_ALIAS_SUBSTR)
            # 锚点 keyword 独立档（B 方案核心：不再蹭 proper-noun 150）
            if any(t == al for al in a_al):
                best = max(best, PKG_ANCHOR_KW_EXACT)
            elif any(t in al for al in a_al):
                best = max(best, PKG_ANCHOR_KW_SUBSTR)
            # title 命中
            if any(t in title_l for t in terms):
                best = max(best, C.PKG_TITLE_SUBSTR)
            # tag 命中
            if any(t in tg for tg in tags_l):
                best = max(best, C.PKG_TAG_SUBSTR)
            # summary 命中
            if any(t in sum_l for t in terms):
                best = max(best, C.PKG_SUMMARY_SUBSTR)
            # 垃圾二元只给极小分
            if _is_garbage_bigram(t):
                best = min(best, C.PKG_GARBAGE_BIGRAM) if best else C.PKG_GARBAGE_BIGRAM
            s += best
        if "trivial" in tags_l:
            s -= C.PKG_TRIVIAL_PENALTY
        return s

    def resolve_two_layer(self, q, top_k=10, scope=None):
        """复刻生产 resolve_two_layer，仅改锚点并入逻辑：keyword 走 anchor_kw，Chapter 仍进 other_aliases。"""
        import re, sqlite3
        if not q or not q.strip():
            return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}
        terms = [t.strip() for t in re.split(r"[\s,，]+", q.strip()) if t.strip()]
        if not terms:
            return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}

        cx = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            rows = cx.execute(
                "SELECT filepath, package_id, title, summary, person, topic, location, tags, anchors "
                "FROM events"
            ).fetchall()
        finally:
            cx.close()
        if not rows:
            return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}

        def flat(jstr):
            try:
                return _flat_variants(jstr)
            except Exception:
                try:
                    d = json.loads(jstr) if jstr else {}
                except Exception:
                    d = {}
                if isinstance(d, dict):
                    out = []
                    for k, vs in d.items():
                        out.append(str(k))
                        out.extend(str(v) for v in (vs or []))
                    return out
                return []

        term_dir_best, term_dir_files = {}, {}
        for t in terms:
            ql = t.lower().strip()
            tb, tf = {}, {}
            for fp, pid, title, summary, pj, tj, lj, tags_j, aj in rows:
                rid = os.path.splitext(os.path.basename(fp))[0]
                person_aliases = flat(pj)
                other_aliases = flat(tj) + flat(lj)
                # B 方案：锚点 keyword 分离到 anchor_kw（独立档），Chapter 仍进 other_aliases
                anchor_kw = []
                try:
                    for a in (json.loads(aj) if aj else []):
                        if isinstance(a, dict):
                            other_aliases.append(str(a.get("Chapter") or ""))
                            anchor_kw.extend(str(k) for k in (a.get("keywords") or []))
                except Exception:
                    pass
                try:
                    tags = json.loads(tags_j) if tags_j else []
                except Exception:
                    tags = []
                s = self._score(ql, rid, title, summary, person_aliases, other_aliases, tags, anchor_kw)
                if s > 0:
                    if pid not in tb or s > tb[pid]:
                        tb[pid] = s
                    tf.setdefault(pid, []).append((rid, title, summary, s, fp))
            term_dir_best[t], term_dir_files[t] = tb, tf

        def aggregate_dir(pid):
            seen = {}
            for t in terms:
                for (rid, title, summary, s, fp) in term_dir_files.get(t, {}).get(pid, []):
                    if fp not in seen or s > seen[fp][3]:
                        seen[fp] = (rid, title, summary, s, fp)
            return sorted(seen.values(), key=lambda x: -x[3])

        if scope:
            f_in = aggregate_dir(scope)
            if not f_in:
                return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}
            if len(f_in) >= 2:
                fc = [{"package_id": scope, "title": r[1], "filepath": r[4],
                       "summary": r[2], "score": round(float(r[3]), 2)} for r in f_in]
                return {"stage": "file", "dirs": [], "files": fc, "hit": None, "results": fc}
            h = f_in[0]
            hit = {"package_id": scope, "title": h[1], "filepath": h[4],
                   "summary": h[2], "score": round(float(h[3]), 2)}
            return {"stage": "hit", "dirs": [], "files": [], "hit": hit, "results": [hit]}

        dir_best, dir_files = {}, {}
        all_pids = {pid for (_, pid, *_rest) in rows}
        for pid in all_pids:
            hit_terms = [t for t in terms if pid in term_dir_best.get(t, {})]
            if len(hit_terms) < len(terms):
                continue
            dir_best[pid] = max(term_dir_best[t][pid] for t in hit_terms)
            dir_files[pid] = aggregate_dir(pid)

        if not dir_best:
            return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}

        dir_ranked = sorted(dir_best.items(), key=lambda x: -x[1])
        cut = __import__("hma.recall_obscure", fromlist=["waterfall_cut"]).waterfall_cut(
            [(p, "", "", "", s) for p, s in dir_ranked], C.CUTOFF_GAP_FLOOR)
        kept = [e[0] for e in cut]
        if len(kept) == 1:
            top_dirs = kept
        else:
            tl = [t.lower() for t in terms]
            title_match = [p for p in kept if any(t in p.split("/")[-1].lower() for t in tl)]
            top_dirs = title_match if len(title_match) == 1 else kept
        if len(top_dirs) >= 2:
            cands = []
            for p in top_dirs:
                files = dir_files[p]
                titles = []
                for (_, t, _, _, _) in files:
                    if t not in titles:
                        titles.append(t)
                cands.append({"package_id": p, "title": files[0][1] if files else p,
                              "score": round(float(dir_best[p]), 2), "files": titles[:8]})
            return {"stage": "dir", "dirs": cands, "files": [], "hit": None, "results": cands}

        locked = top_dirs[0]
        f_in = dir_files[locked]
        if len(f_in) >= 2:
            fc = [{"package_id": locked, "title": r[1], "filepath": r[4],
                   "summary": r[2], "score": round(float(r[3]), 2)} for r in f_in]
            return {"stage": "file", "dirs": [], "files": fc, "hit": None, "results": fc}
        h = f_in[0]
        hit = {"package_id": locked, "title": h[1], "filepath": h[4],
               "summary": h[2], "score": round(float(h[3]), 2)}
        return {"stage": "hit", "dirs": [], "files": [], "hit": hit, "results": [hit]}


EXPECT = {
    "示例事件": {"原创角色/示例角色"},
    "示例信物": {"物品/示例信物"},
    "示例角色": {"原创角色/示例角色"},
    "示例角色": {"原创角色/示例角色"},
    "唱片": {"原创角色/示例角色"},
    "布达佩斯": {"物品/示例信物", "物品/苍穹之泪", "原创角色/示例角色"},
    "示例地点": {"原创角色/示例角色"},
    "铸造厂": {"原创角色/示例角色"},
    "示例设定": {"原创角色/示例角色"},
    "示例别名": {"物品/示例信物", "原创角色/示例角色"},
    "示例协议": {"原创角色/示例角色"},
    "苍穹之泪": {"物品/苍穹之泪"},
}

def pcands(env):
    st = env["stage"]
    if st == "hit":
        return st, [env["hit"]["package_id"]]
    if st == "dir":
        return st, [d["package_id"] for d in env.get("dirs", [])]
    if st == "file":
        return st, [f["package_id"] for f in env.get("files", [])]
    return st, []

if __name__ == "__main__":
    m = MemorySandbox(r"E:/BaiduNetdiskDownload/项目/AIMH/memory")  # 只读索引，不碰生产文件
    env0 = m.resolve_two_layer("示例事件")
    assert env0["stage"] == "hit", "子类 _score/_resolve 覆盖未生效!"
    print(f"{'query':<14} | {'结果(stage + 包)':<60} | 判定")
    print("-" * 100)
    fails = 0
    for q in EXPECT:
        st, c = pcands(m.resolve_two_layer(q))
        ok = set(c) == EXPECT[q]
        if not ok:
            fails += 1
        print(f"{q:<14} | {st+' '+str(c):<60} | {'OK' if ok else 'FAIL <--'}")
        if not ok:
            print(f"{'':<14} |   期望 {sorted(EXPECT[q])}")
    # 哲学：重点验证 B 方案治本——返回 tag 含「哲学」的随笔/论文
    st, c = pcands(m.resolve_two_layer("哲学"))
    ok_essay = any("文章/随笔" in p for p in c)
    ok_paper = any("西西弗斯" in p for p in c)
    ok_phil = ok_essay and ok_paper
    if not ok_phil:
        fails += 1
    print(f"{'哲学':<14} | {st+' '+str(c):<60} | {'OK' if ok_phil else 'FAIL <--'}  (随笔{ok_essay}/论文{ok_paper})")
    m.close()
    print("-" * 100)
    print(f"沙箱 B 通过 {13-fails}/13, 失败 {fails}")
    sys.exit(1 if fails else 0)
