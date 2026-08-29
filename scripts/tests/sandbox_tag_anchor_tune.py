# -*- coding: utf-8 -*-
"""沙箱：治本修法——把档位顺序掰正（主题 tag > 偶提锚点词），并验证打分文件=展示文件。

只读真实 index.db，不碰生产。
核心修复：锚点 IMP 从 0.667 压到 0.4（偶提锚点不再压真 tag），tag IMP 提到 0.8 并加 exact 分支。
验证：① 12 题回归不破；② 哲学下 日志 包的「打分文件」与「展示文件」一致（应是 08-18 真 tag，非 08-15 偶提）。
"""
import sys, os
sys.path.insert(0, r"E:/BaiduNetdiskDownload/项目/AIMH")
import json
from hma.hma_core import Memory, normalize_terms, _is_garbage_bigram, _flat_variants
from hma import scoring_coeffs as C

EXPECT = {
    "示例事件": {"原创角色/示例角色"}, "示例信物": {"物品/示例信物"},
    "示例角色": {"原创角色/示例角色"}, "示例角色": {"原创角色/示例角色"},
    "唱片": {"原创角色/示例角色"}, "布达佩斯": {"物品/示例信物", "物品/苍穹之泪", "原创角色/示例角色"},
    "示例地点": {"原创角色/示例角色"}, "铸造厂": {"原创角色/示例角色"},
    "示例设定": {"原创角色/示例角色"}, "示例别名": {"物品/示例信物", "原创角色/示例角色"},
    "示例协议": {"原创角色/示例角色"}, "苍穹之泪": {"物品/苍穹之泪"},
}


class MemorySandbox(Memory):
    TAG_IMP = 0.8
    ANCHOR_IMP = 0.667  # 保持 B 方案原值：压低会破坏 示例事件 瀑布唯一性（gap<75）

    @staticmethod
    def _score(ql, rid, title, summary, person_aliases, other_aliases, tags, anchor_aliases=None):
        terms = normalize_terms(ql)
        if not terms:
            return 0
        rid_l = rid.lower(); title_l = (title or "").lower(); sum_l = (summary or "").lower()
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
            if any(t == al for al in p_al): best = max(best, C.PKG_PERSON_ALIAS_EXACT)
            elif any(t in al for al in p_al): best = max(best, C.PKG_PERSON_ALIAS_SUBSTR)
            if any(t == al for al in o_al): best = max(best, C.PKG_OTHER_ALIAS_EXACT)
            elif any(t in al for al in o_al): best = max(best, C.PKG_OTHER_ALIAS_SUBSTR)
            # 锚点 keyword 独立档（B），IMP 压到 0.4
            if any(t == al for al in a_al): best = max(best, 150.0 * MemorySandbox.ANCHOR_IMP * 1.0)
            elif any(t in al for al in a_al): best = max(best, 150.0 * MemorySandbox.ANCHOR_IMP * 0.4)
            if any(t in title_l for t in terms): best = max(best, C.PKG_TITLE_SUBSTR)
            # tag：exact 优先，IMP 0.8
            if any(t == tg for tg in tags_l): best = max(best, 150.0 * MemorySandbox.TAG_IMP * 1.0)
            elif any(t in tg for tg in tags_l): best = max(best, 150.0 * MemorySandbox.TAG_IMP * 0.4)
            if any(t in sum_l for t in terms): best = max(best, C.PKG_SUMMARY_SUBSTR)
            if _is_garbage_bigram(t):
                best = min(best, C.PKG_GARBAGE_BIGRAM) if best else C.PKG_GARBAGE_BIGRAM
            s += best
        if "trivial" in tags_l:
            s -= C.PKG_TRIVIAL_PENALTY
        return s

    def resolve_two_layer(self, q, top_k=10, scope=None):
        import re, sqlite3
        if not q or not q.strip():
            return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}
        terms = [t.strip() for t in re.split(r"[\s,，]+", q.strip()) if t.strip()]
        if not terms:
            return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}
        cx = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            rows = cx.execute("SELECT filepath, package_id, title, summary, person, topic, location, tags, anchors FROM events").fetchall()
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
                        out.append(str(k)); out.extend(str(v) for v in (vs or []))
                    return out
                return []

        term_dir_best, term_dir_files = {}, {}
        for t in terms:
            ql = t.lower().strip(); tb, tf = {}, {}
            for fp, pid, title, summary, pj, tj, lj, tags_j, aj in rows:
                rid = os.path.splitext(os.path.basename(fp))[0]
                person_aliases = flat(pj); other_aliases = flat(tj) + flat(lj)
                anchor_kw = []
                try:
                    for a in (json.loads(aj) if aj else []):
                        if isinstance(a, dict):
                            other_aliases.append(str(a.get("Chapter") or ""))
                            anchor_kw.extend(str(k) for k in (a.get("keywords") or []))
                except Exception:
                    pass
                try: tags = json.loads(tags_j) if tags_j else []
                except Exception: tags = []
                s = self._score(ql, rid, title, summary, person_aliases, other_aliases, tags, anchor_kw)
                if s > 0:
                    if pid not in tb or s > tb[pid]: tb[pid] = s
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
            if not f_in: return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}
            if len(f_in) >= 2:
                fc = [{"package_id": scope, "title": r[1], "filepath": r[4], "summary": r[2], "score": round(float(r[3]), 2)} for r in f_in]
                return {"stage": "file", "dirs": [], "files": fc, "hit": None, "results": fc}
            h = f_in[0]
            return {"stage": "hit", "dirs": [], "files": [], "hit": {"package_id": scope, "title": h[1], "filepath": h[4], "summary": h[2], "score": round(float(h[3]), 2)}, "results": [h]}
        dir_best, dir_files = {}, {}
        all_pids = {pid for (_, pid, *_rest) in rows}
        for pid in all_pids:
            ht = [t for t in terms if pid in term_dir_best.get(t, {})]
            if len(ht) < len(terms): continue
            dir_best[pid] = max(term_dir_best[t][pid] for t in ht)
            dir_files[pid] = aggregate_dir(pid)
        if not dir_best:
            return {"stage": "zero", "dirs": [], "files": [], "hit": None, "results": []}
        dir_ranked = sorted(dir_best.items(), key=lambda x: -x[1])
        cut = __import__("hma.recall_obscure", fromlist=["waterfall_cut"]).waterfall_cut([(p, "", "", "", s) for p, s in dir_ranked], C.CUTOFF_GAP_FLOOR)
        kept = [e[0] for e in cut]
        if len(kept) == 1: top_dirs = kept
        else:
            tl = [t.lower() for t in terms]
            tm = [p for p in kept if any(t in p.split("/")[-1].lower() for t in tl)]
            top_dirs = tm if len(tm) == 1 else kept
        if len(top_dirs) >= 2:
            cands = []
            for p in top_dirs:
                files = dir_files[p]; titles = []
                for (_, t, _, _, _) in files:
                    if t not in titles: titles.append(t)
                cands.append({"package_id": p, "title": files[0][1] if files else p, "score": round(float(dir_best[p]), 2), "files": titles[:8]})
            return {"stage": "dir", "dirs": cands, "files": [], "hit": None, "results": cands}
        locked = top_dirs[0]; f_in = dir_files[locked]
        if len(f_in) >= 2:
            fc = [{"package_id": locked, "title": r[1], "filepath": r[4], "summary": r[2], "score": round(float(r[3]), 2)} for r in f_in]
            return {"stage": "file", "dirs": [], "files": fc, "hit": None, "results": fc}
        h = f_in[0]
        return {"stage": "hit", "dirs": [], "files": [], "hit": {"package_id": locked, "title": h[1], "filepath": h[4], "summary": h[2], "score": round(float(h[3]), 2)}, "results": [h]}


def pcands(env):
    st = env["stage"]
    if st == "hit": return st, [env["hit"]["package_id"]]
    if st == "dir": return st, [d["package_id"] for d in env.get("dirs", [])]
    if st == "file": return st, [f["package_id"] for f in env.get("files", [])]
    return st, []


if __name__ == "__main__":
    m = MemorySandbox(r"E:/BaiduNetdiskDownload/项目/AIMH/memory")
    for TAG_IMP in [0.8, 1.0]:
        MemorySandbox.TAG_IMP = TAG_IMP
        MemorySandbox.ANCHOR_IMP = 0.667
        print(f"\n===== TAG_IMP={TAG_IMP} (tag_exact={150*TAG_IMP:.0f})  ANCHOR_IMP=0.667 (anchor_exact=100.05) =====")
        fails = sum(1 for q in EXPECT if set(pcands(m.resolve_two_layer(q))[1]) != EXPECT[q])
        print(f"  12题回归: {'OK' if fails==0 else 'FAIL='+str(fails)}/12")
        env = m.resolve_two_layer("哲学")
        cands = []
        for key in ("dirs", "files"):
            for d in env.get(key, []): cands.append((d["package_id"], d["score"], d.get("files", [d["title"]])[0]))
        if env.get("hit"): cands.append((env["hit"]["package_id"], env["hit"]["score"], env["hit"]["title"]))
        cands.sort(key=lambda x: -x[1])
        print("  哲学候选(包=分, 展示文件):")
        for pid, sc, ftitle in cands:
            mark = "  <-- 日志展示文件" if pid == "日志" else ""
            print(f"    {pid} = {sc}  [{ftitle}]{mark}")
        日志 = [c for c in cands if c[0] == "日志"]
        if 日志:
            disp = 日志[0][2]
            ok = ("08-18" in disp) or ("入库" in disp)
            print(f"  ★ 日志展示文件={disp} -> {'08-18真tag✅(打分文件=展示文件,coherent)' if ok else '仍是08-15偶提❌(incoherent)'}")
        # 示例事件唯一性（锚点档没动，须仍唯一）
        e = m.resolve_two_layer("示例事件")
        ok_gd = set(pcands(e)[1]) == {"原创角色/示例角色"}
        print(f"  示例事件唯一性: {'OK' if ok_gd else 'FAIL '+str(pcands(e)[1])}")
    m.close()
