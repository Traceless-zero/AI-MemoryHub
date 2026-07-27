"""
HMA - Hybrid Memory Architecture (AM 正文 + 薄 CEMA 索引)
==========================================================

零依赖核心库。设计原则（来自 hybrid-memory-architecture.md）：

  1. 前后台严格 1:1：每个事件包 = 一个 .md 正文 + 索引中恰好一条记录
  2. .md 是权威源：SQLite 索引可由所有 .md 的 front-matter 重建
  3. 无状态检索：确定性索引查找（关键词/别名/Tag），不依赖热度/权重/新鲜度
  4. 廉价存储、不遗忘：正文默认冷存储，按需按 ID 取
  5. 主题而非时间线：写入即按事件分类
  6. Agent 直写：LLM 直接写/改 .md，索引 upsert 是确定性微操作

仅使用 Python 标准库（sqlite3 / json / re / os / hashlib）。
"""

import os
import re
import json
import shutil
import sqlite3
from datetime import date

# 变更快照系统已废弃（R59 续3）：write 不再落 changes/，
# 修改标记改由 front-matter 的 `updated:` 字段承担（每次 write 刷新）。


# ---------------------------------------------------------------------------
# 事件包：front-matter（索引字段）+ 正文（语义内容）
# ---------------------------------------------------------------------------

class EventPackage:
    """一个事件包：YAML front-matter + Markdown 正文。"""

    def __init__(self, id, title="", summary="", aliases=None, tags=None,
                 linked=None, created=None, updated=None, body="", anchors=None):
        self.id = id
        self.title = title
        self.summary = summary
        self.aliases = aliases or []
        self.tags = tags or []
        self.linked = linked or []
        self.created = created or str(date.today())
        self.updated = updated or str(date.today())
        self.body = body
        self.anchors = anchors or []
        # 来源路径（读取时回填；非 front-matter 字段，不参与序列化）。
        # link() 等「读改写」操作靠它把包写回原始目录，防止被句柄根劫走。
        self.path = None

    # ---- 序列化（写 .md）------------------------------------------------
    @staticmethod
    def _fmt_list(values):
        out = []
        for v in values:
            v = str(v)
            if ("," in v) or ('"' in v) or ("'" in v):
                v = '"' + v.replace('"', "'") + '"'
            out.append(v)
        return "[ " + ", ".join(out) + " ]"

    def to_markdown(self):
        fm = [
            "---",
            f"id: {self.id}",
            f"title: {self.title}",
            f"summary: {self.summary}",
            f"aliases: {self._fmt_list(self.aliases)}",
            f"tags: {self._fmt_list(self.tags)}",
            f"linked: {self._fmt_list(self.linked)}",
            *([f"anchors: {json.dumps(self.anchors, ensure_ascii=False)}"]
              if self.anchors else []),
            f"created: {self.created}",
            f"updated: {self.updated}",
            "---",
            "",
            self.body if self.body.endswith("\n") else self.body + "\n",
        ]
        return "\n".join(fm)

    # ---- 反序列化（读 .md）----------------------------------------------
    @classmethod
    def from_markdown(cls, text, filepath=None):
        if not text.startswith("---"):
            # 无 front-matter：整篇当正文，id 由文件名推断
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body=text.strip())
        parts = text.split("---", 2)
        if len(parts) < 3:
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body=text.strip())
        fm_text, body = parts[1], parts[2].lstrip("\n")
        fm = cls._parse_fm(fm_text)
        return cls(
            id=fm.get("id", ""),
            title=fm.get("title", ""),
            summary=fm.get("summary", ""),
            aliases=fm.get("aliases", []),
            tags=fm.get("tags", []),
            linked=fm.get("linked", []),
            anchors=fm.get("anchors", []),
            created=fm.get("created", ""),
            updated=fm.get("updated", ""),
            body=body.strip(),
        )

    @staticmethod
    def _parse_value(v):
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            if not inner:
                return []
            # 简易：按逗号切，去引号
            out = []
            for it in inner.split(","):
                it = it.strip().strip('"').strip("'").strip()
                if it:
                    out.append(it)
            return out
        return v

    @staticmethod
    def _parse_fm(text):
        data = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k = k.strip()
            if k == "anchors":
                try:
                    data[k] = json.loads(v.strip())
                except Exception:
                    data[k] = []
            else:
                data[k] = EventPackage._parse_value(v)
        return data


# ---------------------------------------------------------------------------
# 统一前台 db：仓库根 memory/ 下只有【一个】index.db
# ---------------------------------------------------------------------------
REPO_DIR_NAMES = ("memory", ".memory")   # R59 用户拍板去掉"."；.memory 留作旧库兼容


def _repo_of(root):
    """从任意包目录向上找到 memory/（或旧式 .memory/）仓库根祖先。"""
    p = os.path.abspath(root)
    while True:
        if os.path.basename(p) in REPO_DIR_NAMES:
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return os.path.abspath(root)   # 找不到仓库根祖先：退化以 root 自身为仓
        p = parent


def _pkg_id(root, repo):
    """包标识 = 包目录相对仓库根的路径（如 原创角色/luzhao）。

    统一规范为【正斜杠】分隔——与用户心智模型、SKILL.md 示例
    （哲学/尼采、cache/archive）、跨平台一致。否则 Windows 会存成
    `哲学\尼采`（反斜杠），而用户/agent 传的是 `哲学/尼采`，
    精确匹配会静默失配。filepath 列仍存 OS 原生绝对路径
    （那是真实文件路径，非逻辑 id，不需要归一）。
    """
    r = os.path.abspath(root)
    rp = os.path.abspath(repo)
    if r == rp:
        return ""          # root 即仓库根：repo 级句柄（全局）
    return os.path.relpath(r, rp).replace(os.sep, "/")


# ---------------------------------------------------------------------------
# 内存存储：管理 memory/ 目录 + 统一 SQLite 薄索引
# ---------------------------------------------------------------------------

class Memory:
    """混合记忆存储。

    统一前台 db（CEMA「前后台严格 1:1 铁律」的落地）：
    仓库根 memory/ 下只有【一个】index.db，所有事件包的索引都落在这张
    表里，用 package_id 列区分「属于哪个包」。每个事件包仍对应索引里
    恰好一条记录（id 唯一）——1:1 不变；package_id 只是把记录归到某包，
    便于「一个自动化脚本直接装卸某个记忆文件夹」（install/uninstall）。

    root 参数语义不变：仍是「某个包目录」（如 memory/原创角色/luzhao）；
    db 自动落在它的 memory/ 祖先下的 index.db，package_id 由 root 推出。
    """

    def __init__(self, root):
        self.root = root
        self.repo = _repo_of(root)
        self.db_path = os.path.join(self.repo, "index.db")
        self.package_id = _pkg_id(root, self.repo)
        # R50：移除 events/ 包装层，包目录即事件 .md 容器（双层级）
        self.events_dir = root
        os.makedirs(self.repo, exist_ok=True)        # 统一 db 所在目录
        os.makedirs(self.root, exist_ok=True)         # 包目录（写 .md 用）
        # 单例持久连接（autocommit），工具场景单线程，显式 close() 释放锁
        self._cx = None
        self._init_db()

    def close(self):
        """释放底层 SQLite 连接（删除/重建索引前调用）。"""
        if self._cx is not None:
            try:
                self._cx.close()
            except Exception:
                pass
            self._cx = None

    # ---- 索引层（SQLite 薄表，可由 front-matter 重建）--------------------
    def _conn(self):
        if self._cx is None:
            self._cx = sqlite3.connect(self.db_path, isolation_level=None)
            self._init_db()
        return self._cx

    def _init_db(self):
        c = self._conn()
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id        TEXT,
                package_id TEXT,
                title     TEXT,
                summary   TEXT,
                aliases   TEXT,
                tags      TEXT,
                linked    TEXT,
                filepath  TEXT,
                created   TEXT,
                updated   TEXT,
                embedding BLOB,
                anchors   TEXT,
                PRIMARY KEY (id, package_id)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_pkg ON events(package_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tags ON events(tags)")
        self._ensure_columns()

    def _ensure_columns(self):
        """旧库缺列时 ALTER 补齐，保证向后兼容。"""
        c = self._conn()
        cols = {r[1] for r in c.execute("PRAGMA table_info(events)").fetchall()}
        for col, ctype in [("anchors", "TEXT"), ("package_id", "TEXT")]:
            if col not in cols:
                c.execute(f"ALTER TABLE events ADD COLUMN {col} {ctype}")

    # ---- 写入路径（实时，Agent 直写 .md + 确定性 upsert 索引）-----------
    def write(self, id, title="", summary="", aliases=None, tags=None,
              linked=None, body="", created=None, updated=None,
              anchors=None, embedding=None, trigger=None,
              record_change=True):
        """写/改一个事件包：原子写 .md + upsert 索引。
        anchors: 可选子事件锚点列表 [{title, summary, tags, locator}]，
        挂在同一个 .md 正文上，实现「1 个包 + 多锚点」的细粒度召回。
        trigger: 调用方标识（仅作元信息标签，当前不落任何变更日志；
                 历史曾用于 changes/ 快照审计，R59 续3 已废弃）。
        """
        updated = updated or str(date.today())
        if anchors is None and body:
            anchors = derive_anchors(body)
        pkg = EventPackage(
            id=id, title=title, summary=summary,
            aliases=aliases or [], tags=tags or [], linked=linked or [],
            created=created, updated=updated, body=body,
            anchors=anchors,
        )
        # 若已存在，保留原 created
        existing = self.read(id)
        if existing and existing.created:
            pkg.created = existing.created
        if existing and not created:
            pkg.created = existing.created

        path = os.path.join(self.events_dir, f"{id}.md")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(pkg.to_markdown())
        os.replace(tmp, path)  # 原子落盘，崩溃安全

        self._upsert(pkg, path, embedding)
        return path

    def _upsert(self, pkg, path, embedding=None, package_id=None):
        pid = package_id if package_id is not None else self.package_id
        c = self._conn()
        c.execute("""
            INSERT INTO events
                (id,package_id,title,summary,aliases,tags,linked,
                 filepath,created,updated,embedding,anchors)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id, package_id) DO UPDATE SET
                title=excluded.title, summary=excluded.summary,
                aliases=excluded.aliases, tags=excluded.tags,
                linked=excluded.linked, filepath=excluded.filepath,
                updated=excluded.updated, embedding=excluded.embedding,
                anchors=excluded.anchors
        """, (
            pkg.id, pid, pkg.title, pkg.summary,
            json.dumps(pkg.aliases, ensure_ascii=False),
            json.dumps(pkg.tags, ensure_ascii=False),
            json.dumps(pkg.linked, ensure_ascii=False),
            path, pkg.created, pkg.updated,
            embedding,
            json.dumps(pkg.anchors, ensure_ascii=False),
        ))

    # ---- 关联（单源：front-matter 为真相，索引为视图）--------------------
    def _write_back(self, pkg):
        """把「读改写」后的包写回其【原始目录】。

        R58 修复：link() 曾经统一走 self.write()，而 write() 硬编码落盘到
        self.events_dir（句柄根）。跨包 link 必须用全局 Memory("memory")
        句柄解析 id，于是两个端点被"搬家"到 memory/ 根，产生
        package_id='' 的重复包体。现按 pkg.path（read 回填的来源路径）
        为目标目录开局部句柄写回，文件永远留在原位。
        """
        dst_dir = os.path.dirname(pkg.path) if pkg.path else self.events_dir
        same = os.path.abspath(dst_dir) == os.path.abspath(self.events_dir)
        m = self if same else Memory(dst_dir)
        try:
            m.write(pkg.id, pkg.title, pkg.summary, pkg.aliases, pkg.tags,
                    pkg.linked, pkg.body, created=pkg.created,
                    anchors=pkg.anchors)
        finally:
            if m is not self:
                m.close()

    def link(self, id_a, id_b):
        """双向关联两个事件包：更新两者 front-matter 的 linked。
        每个端点写回各自原始目录（见 _write_back），跨包 link 不再搬家。"""
        a = self.read(id_a)
        b = self.read(id_b)
        if not a or not b:
            missing = [x for x, p in ((id_a, a), (id_b, b)) if not p]
            raise ValueError(f"事件包不存在: {missing}")
        if id_b not in a.linked:
            a.linked.append(id_b)
        if id_a not in b.linked:
            b.linked.append(id_a)
        self._write_back(a)
        self._write_back(b)

    # ---- 检索路径（确定性、无状态、O(n) 全表扫描）-------------------------
    def query(self, q, top_k=5, use_vector=False, package_id=None):
        """确定性检索：关键词命中 id/title/alias/tag/summary。
        返回 [(id, title, summary, score), ...]（已按确定性规则排序）。

        package_id=None（默认）→ 限定在当前 Memory 的包作用域内
        （repo 级句柄 package_id="" 即全局扫描）；传 "" 显式即全局；
        传具体包 id（如 "原创角色/luzhao"）则只扫该包。

        复杂度 O(n)：全表/包 fetchall + 逐行打分。个人记忆规模（<10⁴ 包）
        实测 <50ms。若未来超万级且 json.loads 开销可感，可加 SQL LIKE
        预过滤缩小候选（不改表、可重建、不引入状态），无需倒排/FTS。
        """
        ql = q.lower().strip()
        c = self._conn()
        pid = self.package_id if package_id is None else package_id
        if pid:
            # q-2（嵌套检索）：范围搜"哲学"也命中"哲学/尼采"子树——
            # package_id=?（本节点）OR package_id LIKE ?||'/%'（所有子孙）。
            # 确定性（无热度/新鲜度权重），不破 §13；现有包均扁平，零回归。
            rows = c.execute(
                "SELECT id,title,summary,aliases,tags,linked,updated "
                "FROM events WHERE package_id=? OR package_id LIKE ? || '/%'",
                (pid, pid)).fetchall()
        else:
            rows = c.execute(
                "SELECT id,title,summary,aliases,tags,linked,updated "
                "FROM events").fetchall()

        scored = []
        for rid, title, summary, aliases_j, tags_j, linked_j, updated in rows:
            aliases = json.loads(aliases_j or "[]")
            tags = json.loads(tags_j or "[]")
            s = self._score(ql, rid, title, summary, aliases, tags)
            if s > 0:
                scored.append((rid, title, summary, s, updated))

        # 确定性排序：分数降序 → 更新日期降序 → id 升序
        scored.sort(key=lambda x: (-x[3], x[4] or "", x[0]))
        return [(x[0], x[1], x[2], x[3]) for x in scored[:top_k]]

    def query_anchors(self, q, top_k=5, package_id=None):
        """细粒度召回：在锚点层检索，返回命中的子事件。
        返回 [(pkg_id, anchor_title, anchor_summary, locator, score), ...]。
        用于「1 个包 + 多锚点」场景下的精准故事召回。
        package_id 过滤语义同 query。"""
        ql = q.lower().strip()
        terms = [t for t in re.split(r"\s+", ql) if t]
        if not terms:
            return []
        c = self._conn()
        pid = self.package_id if package_id is None else package_id
        if pid:
            # q-2（嵌套检索）：同 query，范围搜"哲学"也命中"哲学/尼采"子树
            rows = c.execute(
                "SELECT id,anchors FROM events "
                "WHERE package_id=? OR package_id LIKE ? || '/%'",
                (pid, pid)).fetchall()
        else:
            rows = c.execute("SELECT id,anchors FROM events").fetchall()
        scored = []
        for rid, anchors_j in rows:
            try:
                anchors = json.loads(anchors_j or "[]")
            except Exception:
                anchors = []
            for a in anchors:
                at = (a.get("title") or "").lower()
                asum = (a.get("summary") or "").lower()
                atags = [t.lower() for t in (a.get("tags") or [])]
                s = 0
                if ql == at:
                    s += 80
                else:
                    for t in terms:            # 逐词累加：多词全中 > 仅中一词
                        if t in at:
                            s += 50
                for t in terms:
                    if t in asum:
                        s += 30
                for t in atags:
                    if ql == t:
                        s += 40
                    else:
                        for term in terms:
                            if term in t:
                                s += 30
                                break
                if s > 0:
                    scored.append((rid, a.get("title", ""),
                                  a.get("summary", ""),
                                  a.get("locator", a.get("title", "")), s))
        scored.sort(key=lambda x: -x[4])
        return scored[:top_k]

    @staticmethod
    def _score(ql, rid, title, summary, aliases, tags):
        # 多词查询按空白切分；CJK 无空格则整体作为一词
        terms = [t for t in re.split(r"\s+", ql) if t]
        if not terms:
            return 0
        rid_l = rid.lower()
        title_l = (title or "").lower()
        sum_l = (summary or "").lower()
        tags_l = [t.lower() for t in tags]
        aliases_l = [a.lower() for a in aliases]

        s = 0
        # id 命中
        if ql == rid_l:
            s += 100
        elif any(t in rid_l for t in terms):
            s += 30
        # title 命中（整串精确 > 逐词包含）
        if ql == title_l:
            s += 60
        elif any(t in title_l for t in terms):
            s += 60
        # alias
        for al in aliases_l:
            if ql == al:
                s += 50
            elif any(t in al for t in terms):
                s += 40
        # tag（短词精确优先）
        for t in tags_l:
            if ql == t:
                s += 40
            elif any(term in t for term in terms):
                s += 40
        # summary
        if any(t in sum_l for t in terms):
            s += 20
        # 静态分类惩罚（trivial 少注入），非热度/新鲜度
        if "trivial" in tags_l:
            s -= 15
        return s

    # ---- 读取正文（冷存储按需取）------------------------------------------
    def read(self, id, package_id=None):
        """读取事件包正文（db-first 定位 filepath，支持跨包按 id 取）。

        package_id=None（默认）→ 用当前句柄作用域；传 "" → 全局取首个匹配；
        传具体包 id 则限定。索引缺失/路径失效时回退到当前包 events_dir 直读。
        """
        c = self._conn()
        pid = package_id if package_id is not None else self.package_id
        if pid:
            row = c.execute(
                "SELECT filepath FROM events WHERE id=? AND package_id=?",
                (id, pid)).fetchone()
        else:
            row = c.execute(
                "SELECT filepath FROM events WHERE id=? LIMIT 1",
                (id,)).fetchone()
        path = row[0] if (row and row[0]) else None
        if not path or not os.path.exists(path):
            path = os.path.join(self.events_dir, f"{id}.md")
            if not os.path.exists(path):
                return None
        with open(path, "r", encoding="utf-8") as f:
            pkg = EventPackage.from_markdown(f.read(), path)
        pkg.path = path          # 回填来源路径，供 link() 写回原目录
        return pkg

    def read_body(self, id):
        pkg = self.read(id)
        return pkg.body if pkg else None

    def read_section(self, id, heading):
        """按需读取正文里某个 ### / ## 小标题下的段落（锚点召回）。"""
        pkg = self.read(id)
        if not pkg:
            return None
        lines = pkg.body.splitlines()
        start, level = None, None
        for i, ln in enumerate(lines):
            m = re.match(r"^(#{2,4})\s+(.*)$", ln)
            if m and heading in m.group(2):
                start, level = i, len(m.group(1))
                break
        if start is None:
            return None
        out = [lines[start]]
        for j in range(start + 1, len(lines)):
            m = re.match(r"^(#{2,4})\s+", lines[j])
            if m and len(m.group(1)) <= level:
                break
            out.append(lines[j])
        return "\n".join(out).strip()

    # ---- 重建（索引损坏 = 重新扫描，不丢数据）-----------------------------
    def rebuild(self):
        """扫包目录下的事件 .md 的 front-matter，全量重建【当前包】索引。

        只删当前 package_id 的索引行（DELETE ... WHERE package_id=?），
        不清整库——其余包的索引行不受任何影响。这正是不再「每包一 db」
        后仍能安全装卸单个记忆文件夹的底气：rebuild 永远只动自己那一份。
        """
        self._init_db()   # 保证表存在（即便 db 被外部删除后重开）
        c = self._conn()
        c.execute("DELETE FROM events WHERE package_id=?", (self.package_id,))
        count = 0
        if os.path.isdir(self.root):
            for fn in os.listdir(self.root):
                if not fn.endswith(".md"):
                    continue
                if fn.endswith(".tmp"):
                    continue
                path = os.path.join(self.root, fn)
                if not os.path.isfile(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    pkg = EventPackage.from_markdown(f.read(), path)
                if not pkg.id:
                    continue
                self._upsert(pkg, path)
                count += 1
        return count

    def rebuild_all(self, progress=None):
        """遍历仓库根下所有包目录，全量重建统一索引（清库后逐包重建）。

        一个自动化脚本即可整体刷新：
            python -m hma.engine rebuild-all --root memory

        progress：可选回调 progress(stage, message)，用于 GUI 逐包回报进度
        （stage ∈ {scan, pkg, done}）。默认 None = 静默（兼容旧调用）。
        """
        self._init_db()
        c = self._conn()
        c.execute("DELETE FROM events")   # 清库，再逐包重建
        count = 0
        repo = self.repo
        if progress:
            progress("scan", "开始全量重建索引（清除旧索引后逐包重扫）…")
        for dirpath, dirnames, filenames in os.walk(repo):
            # 跳过派生缓存：根级 目录结构树.md 自带 id front-matter，
            # 若纳入会被误索成 package_id='' 的游离根行
            if "目录结构树.md" in filenames:
                filenames.remove("目录结构树.md")
            # R50：一个"包"= 直接含可解析事件 .md 的目录
            # （不再要求 events/ 子目录；命名空间目录自身不含 .md → 不会误判）
            md_events = [fn for fn in filenames
                         if fn.endswith(".md") and not fn.endswith(".tmp")
                         and os.path.isfile(os.path.join(dirpath, fn))]
            if not md_events:
                continue
            pkg_dir = dirpath
            pid = _pkg_id(pkg_dir, repo)
            if progress:
                progress("pkg", "%s  (%d 事件)" % (pid or "(仓库根)", len(md_events)))
            for fn in md_events:
                path = os.path.join(pkg_dir, fn)
                with open(path, "r", encoding="utf-8") as f:
                    pkg = EventPackage.from_markdown(f.read(), path)
                if not pkg.id:
                    continue
                self._upsert(pkg, path, package_id=pid)
                count += 1
        if progress:
            progress("done", "共重建 %d 条事件索引" % count)
        return count

    # ---- 装卸（一个脚本直接装/卸某个记忆文件夹）-------------------------
    def install(self, pkg_dir, rm=False):
        """把一个记忆文件夹（直接含事件 .md）装入统一索引。

        等价于：以该包目录推导仓库根、清掉该 package_id 旧行、扫事件 .md 重插。
        只动目标包自己的索引行，其余包不受影响。
        可选 rm=True：装完后删除【源】文件夹（谨慎！已装内容已在统一索引）。
        """
        pkg_dir = os.path.abspath(pkg_dir)
        # R50：合法包 = 直接含事件 .md（不再要求 events/ 子目录）
        mds = [fn for fn in os.listdir(pkg_dir)
                if fn.endswith(".md") and not fn.endswith(".tmp")
                and os.path.isfile(os.path.join(pkg_dir, fn))] \
            if os.path.isdir(pkg_dir) else []
        if not mds:
            raise ValueError(f"不是合法记忆包（缺事件 .md）：{pkg_dir}")
        pid = _pkg_id(pkg_dir, self.repo)
        c = self._conn()
        c.execute("DELETE FROM events WHERE package_id=?", (pid,))
        count = 0
        for fn in sorted(mds):
            path = os.path.join(pkg_dir, fn)
            with open(path, "r", encoding="utf-8") as f:
                pkg = EventPackage.from_markdown(f.read(), path)
            if not pkg.id:
                continue
            self._upsert(pkg, path, package_id=pid)
            count += 1
        if rm:
            shutil.rmtree(pkg_dir, ignore_errors=True)
        return count

    def uninstall(self, package_id, rm=False):
        """从统一索引卸下某个记忆文件夹（按 package_id 删索引行）。

        可选 rm=True：同时删除磁盘上的包文件夹（<repo>/<package_id>）。
        package_id 为空时拒绝（避免误删仓库根）。
        """
        if not package_id:
            raise ValueError("package_id 为空：拒绝卸载仓库根")
        c = self._conn()
        c.execute("DELETE FROM events WHERE package_id=?", (package_id,))
        if rm:
            target = os.path.join(self.repo, package_id)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
        return package_id

    # ---- 工具 -----------------------------------------------------------------
    def list_all(self):
        c = self._conn()
        if self.package_id:
            return c.execute(
                "SELECT id,title,tags,updated FROM events "
                "WHERE package_id=? ORDER BY updated DESC, id",
                (self.package_id,)).fetchall()
        return c.execute(
            "SELECT id,title,tags,updated FROM events "
            "ORDER BY updated DESC, id").fetchall()

    def list_summaries(self):
        """(id, title, summary) 列表，仅供关联发现等内部用途，仅扫索引。
        当前包作用域（repo 级句柄 package_id="" 则全局）。"""
        c = self._conn()
        if self.package_id:
            rows = c.execute(
                "SELECT id,title,summary FROM events "
                "WHERE package_id=? ORDER BY updated DESC, id",
                (self.package_id,)).fetchall()
        else:
            rows = c.execute(
                "SELECT id,title,summary FROM events "
                "ORDER BY updated DESC, id").fetchall()
        return [(r[0], r[1] or "", r[2] or "") for r in rows]


# ---------------------------------------------------------------------------
# 锚点派生（确定性、OC 无关，纯 stdlib；供 EXE 打包安全复用）
# ---------------------------------------------------------------------------
# 标题行：`#`~`######`，捕获层级与标题文本（兼容行尾 `#` 闭包）
_anchor_heading_re = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")

# 句末切分（中英文句号/问叹/分号）
_anchor_sent_split = re.compile(r"(?<=[。！？!?；;\.])\s*")

# 表格分隔行（如 `| --- | --- |`）
_anchor_table_sep = re.compile(r"^[\s|:\-|]+$")


def _anchor_clean_inline(md):
    """去 markdown 行内噪音，保留可读文字。"""
    md = re.sub(r"`[^`]*`", "", md)                       # 行内代码
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)             # 图片
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)         # 链接 → 文字
    md = re.sub(r"[*_~]{1,3}([^*_~]+)[*_~]{1,3}", r"\1", md)  # 强调
    md = re.sub(r"^#+\s*", "", md)                            # 残留行首 #
    return md.strip()


def _anchor_first_sentence(text):
    """取正文首句（跳过空行/表格行/标题行，到第一个句末标点）。"""
    text = (text or "").strip()
    if not text:
        return ""
    for raw in re.split(r"\n+", text):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("|") or _anchor_table_sep.match(line):
            continue  # 表格/分隔行不参与摘要
        parts = _anchor_sent_split.split(line)
        if parts and parts[0].strip():
            return parts[0].strip()
    return ""


def derive_anchors(md_text, max_level=2):
    """从 Markdown 正文派生章级锚点列表。

    返回 [{title, locator, summary, tags}, ...]。
    默认 max_level=2：只取 `##` 章级（通用规则，召回单元=叙事自洽大章）。
    max_level=4 → `##`/`###`/`####` 全部派生锚点（论文体最小单元）。
    """
    lines = (md_text or "").splitlines()
    heads = []
    for i, ln in enumerate(lines):
        m = _anchor_heading_re.match(ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))

    anchors = []
    for k, (i, lvl, title) in enumerate(heads):
        if not (2 <= lvl <= max_level):
            continue
        body_start = i + 1
        body_end = len(lines)
        for j in range(k + 1, len(heads)):
            if heads[j][1] <= lvl:
                body_end = heads[j][0]
                break
        body = "\n".join(lines[body_start:body_end])
        anchors.append({
            "title": title,
            "locator": title,
            "summary": _anchor_first_sentence(body),
            "tags": [],
        })
    return anchors


def _anchor_all_heading_texts(md_text):
    """收集正文所有层级标题文本（任意 #~######），用于区分
    '用户手写锚定的子节(### 等)' 与 '已删除的 stale 锚点'。"""
    out = []
    for ln in (md_text or "").splitlines():
        m = _anchor_heading_re.match(ln)
        if m:
            out.append(m.group(2).strip())
    return out


def merge_anchors(existing, body, max_level=2):
    """把'自动派生(打底)' 与 '用户手写(覆盖)' 合并为最终锚点列表。

    以 locator(=标题原文) 为键，规则：
      - 正文有个新 ##（existing 无对应）→ 补派生版（自动打底）
      - 已有 ## 且 existing 与派生一致(summary+tags 同) → 原地刷新派生版
      - 已有 ## 但 existing 被手改(summary 或 tags 不同) → 留用户的版本
      - 正文删了某 ##（原 anchor 失效）→ 删
      - 用户手写锚定到非 ## 的子节(### 等，派生不覆盖) → 留
    返回新列表；不修改入参。纯 stdlib、无外部依赖（供 EXE 打包安全）。
    """
    existing = existing or []
    derived = derive_anchors(body, max_level=max_level)
    _derived_by_loc = {a["locator"]: a for a in derived}
    all_headings = set(_anchor_all_heading_texts(body))

    result = []
    seen = set()
    for d in derived:
        loc = d["locator"]
        seen.add(loc)
        e = None
        for x in existing:
            if x.get("locator") == loc:
                e = x
                break
        if e is None:
            result.append(d)                                  # 新 ## → 打底
        elif e.get("summary") == d["summary"] and e.get("tags") == d["tags"]:
            result.append(d)                                  # 仍=派生 → 刷新(无害)
        else:
            result.append(e)                                  # 手改 → 留用户版
    for e in existing:
        loc = e.get("locator")
        if loc in seen:
            continue                                          # 上面已处理
        if loc in all_headings:
            result.append(e)                                  # 用户锚定子节(###等) → 留
        # else: 真 stale（## 被删）→ 丢弃
    return result


if __name__ == "__main__":
    import tempfile
    d = tempfile.mkdtemp()
    m = Memory(os.path.join(d, ".memory"))
    m.write("proj-x", "X 项目", "架构决策", ["x架构"], ["project", "decision"],
            body="# X\n初始综述")
    print("query 'x架构':", m.query("x架构"))
    print("rebuild ->", m.rebuild())
    print("query after rebuild:", m.query("架构"))
