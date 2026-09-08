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
import math
from collections import Counter
from datetime import date, timedelta

# 公共路由层（查询→包/作用域）：从 hma_core 抽出为单一真相源。
# routing 模块惰性导入本模块的符号，故此处顶层导入无循环依赖风险。
from . import routing
from . import scoring_coeffs as C
from . import recall_obscure as ro
from . import fm_yaml
from .event_package import (  # noqa: F401  S2 拆分 re-export：EventPackage 本体与四要素兼容层
    EventPackage, _as_four, _merge_legacy, _four_to_list,
)
from .aggregate_time import (  # noqa: F401  S3 拆分 re-export：时间意图与聚合/硬过滤后端
    TimeHint, parse_time_hint, db_aggregate, time_filter,
    _is_union_query, _time_tiebreak,
)
from .write_path import (  # noqa: F401  S5 拆分 re-export：写入线 Mixin 与路径护栏
    WriteMixin, _in_tree, _safe_md_path,
)
from .retrieval import (  # noqa: F401  S4a 拆分 re-export：机械层与拒答阈值
    _MechanicalLayer, ABSTAIN_KAPPA, ABSTAIN_HIGH_K, ABSTAIN_DEFAULT_MSG,
)
from .retrieval import RetrievalMixin  # noqa: F401  S4b 拆分 re-export
from .retrieval import _PUNCT, _STOPWORDS, _GARBAGE_FUNC, MIN_CANDIDATES  # noqa: F401
from .retrieval import _LOC_WORDS, _FIELD_W, _FIELD_NUDGE, _FIELD_CAP  # noqa: F401
from .retrieval import (  # noqa: F401  S4b 跨线共享函数（本模块经 re-export 继续使用）
    _scope_clause, normalize_terms, _flat_variants, _is_garbage_bigram,
    _anchor_score, _feat_alt_match, _field_term_hit, _norm, _norm_name,
    _share_surname, _search_blob, _entity_key,
)







# 关键词比对加分权重（用户提议“比对到后对这个关键词加权”，模块级常量供 _anchor_score 使用）：
# 查询里的每个关键词一旦在本文块命中，即加固定大分——查询词即用户意图信号，
# 命中即重赏，让“匹配上用户原话关键词”的包压倒性靠前。不依赖 idf 压缩下的稀有度，
# 故在小索引（稀有词 idf 被 +1 地板压扁）也能靠“命中用户原词”翻盘。
# 系数统一迁至 scoring_coeffs.KW_FIXED / KW_BIGRAM_BONUS（单一调参面，消除散落魔法数字）。



# grounding 过注入抑制（反向操作）：四要素/tags 接地展开出的检索词，若跨「≥此包数」
# 的包出现，视为跨包常见词（非判别信号），不再注入成查询词。即「越多包出现的词越
# 不值得当检索词，越少包出现的稀有词才保留作判别」——修 T05/T07 因用户画像包把
# OC 实体/泛词当「产出作品」变体整批注入、把 demo-origin 顶上 TOP 的共现陷阱。
# 门限取小整数（非比例），因小索引下稀有判别词也常只落 1–2 包；3≈9% 的包即算跨包常见。
_GROUND_PKG_GATE = 3








# 字段中心度层级：person 规范名/别名 最靠近身份核心，tags 最边缘。
# 独有弧段排序时，同判别度优先展示更靠近圆心的性质（特异性梯度）。
_FIELD_TIER = {"person": 4, "kw": 3, "topic": 2, "tags": 1, "location": 2}













# ---------------------------------------------------------------------------
# 事件包：front-matter（索引字段）+ 正文（语义内容）
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 统一前台 db：仓库根 memory/ 下只有【一个】index.db
# ---------------------------------------------------------------------------
REPO_DIR_NAMES = ("memory", ".memory")   # R59 用户拍板去掉"."；.memory 留作旧库兼容


def _load_for_index(path):
    """索引构建专用加载：优先仅读 front-matter（省去正文 I/O 与解析）。

    返回 EventPackage；以下情况返回 None（调用方跳过该文件）：
      - 文件读失败 / 不存在（OSError）
      - 脚本派生视图（含 '本文件由脚本派生' 标记）
    正文不进索引（_upsert 不含 body 列），且 anchors 已随写入固化进
    front-matter，故默认跳过正文解析。若 FM 缺 anchors（legacy 包），
    回退 EventPackage.from_markdown 全量解析（从 body 派生），语义与改造前一致。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            # 读足够大的头部以覆盖含鸿篇巨制在内的几乎所有 front-matter（含长 anchors JSON）；
            # 1MB 上限可吞下《战争与和平》级（~360 章 / ~60KB anchors）的 FM 仍留 16x 余量；
            # 若 FM 仍超此上限致锚点 JSON 被截断，from_markdown_fm_only 会因
            # 找不到闭合 '---' 或解析失败回落到全量解析（_load_for_index 的
            # `if not pkg.anchors` 分支），不会索引到损坏的 anchors。
            head = f.read(1048576)   # 1MB：FM 读取上限（不读正文）
    except OSError:
        return None
    # 派生标记只检测文档开头（与 derive_topic_views 派生文件头口径一致）：
    # 此前用全文 1MB 模糊匹配，会误判 design-journal 中在正文深处讨论「派生机制」
    # 的设计文档为派生文件而跳过（daylog设计/存储架构总览/拆包与收录规范 长期漏收）。
    if "本文件由脚本派生" in head[:600]:
        return None
    pkg = EventPackage.from_markdown_fm_only(head, path)
    if not pkg.anchors:
        # legacy 包 FM 无 anchors：全量解析（从 body 派生），保持原语义
        try:
            with open(path, "r", encoding="utf-8") as f:
                pkg = EventPackage.from_markdown(f.read(), path)
        except OSError:
            return None
    return pkg


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



class Memory(_MechanicalLayer, WriteMixin, RetrievalMixin):
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
        """建 V2 索引表；若遇到旧表（含 id/aliases/features/created/updated 列）
        则原地迁移到 V2 结构（建新表→搬运→改名），幂等、可重复调用。"""
        # search_blob 填充态懒判定缓存（每 Memory 实例一次，见 _blob_populated 方法）。
        # 注意属性名不能与同名方法冲突（否则实例属性会遮蔽方法 → 调用报 NoneType
        # not callable），故命名为 _blob_populated_cache。必须在所有可能返回路径前
        # 初始化，否则 _blob_populated() 首访 AttributeError。
        self._blob_populated_cache = None
        c = self._conn()
        exists = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()
        if exists:
            cols = {r[1] for r in c.execute("PRAGMA table_info(events)").fetchall()}
            if "pkage_created" in cols:
                # 已是 V2 表：补 search_blob 列（旧库可能缺）+ 索引即返回
                if "search_blob" not in cols:
                    c.execute("ALTER TABLE events ADD COLUMN search_blob TEXT")
                c.execute("CREATE INDEX IF NOT EXISTS idx_pkg ON events(package_id)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_tags ON events(tags)")
                self._blob_ok = True   # 列已存在；旧行 NULL 由预筛 OR search_blob IS NULL 兜底
                # _blob_populated 已在 _init_db 顶部统一初始化为 None（此处不再重复）
                return
            # —— 旧表 → V2 迁移 ——
            c.execute("""
                CREATE TABLE events_v2 (
                    package_id TEXT, title TEXT, summary TEXT, tags TEXT,
                    linked TEXT, filepath TEXT, pkage_created TEXT,
                    pkage_updated TEXT, embedding BLOB, anchors TEXT,
                    person TEXT, event_date TEXT, location TEXT, topic TEXT,
                    search_blob TEXT,
                    PRIMARY KEY (package_id, filepath)
                )
            """)
            # 旧表可能缺部分新列，COALESCE 兜底空串；aliases/features 列数据由
            # rebuild 时 from_markdown 折叠进四要素 dict（不在此搬运）。
            c.execute("""
                INSERT OR REPLACE INTO events_v2
                    (package_id, title, summary, tags, linked, filepath,
                     pkage_created, pkage_updated, embedding, anchors,
                     person, event_date, location, topic)
                SELECT package_id, title, summary,
                       COALESCE(tags,''), COALESCE(linked,''), COALESCE(filepath,''),
                       COALESCE(created,''), COALESCE(updated,''), embedding,
                       COALESCE(anchors,''), COALESCE(person,''),
                       COALESCE(event_date,''), COALESCE(location,''), COALESCE(topic,'')
                FROM events
            """)
            c.execute("DROP TABLE events")
            c.execute("ALTER TABLE events_v2 RENAME TO events")
        else:
            c.execute("""
                CREATE TABLE events (
                    package_id TEXT, title TEXT, summary TEXT, tags TEXT,
                    linked TEXT, filepath TEXT, pkage_created TEXT,
                    pkage_updated TEXT, embedding BLOB, anchors TEXT,
                    person TEXT, event_date TEXT, location TEXT, topic TEXT,
                    search_blob TEXT,
                    PRIMARY KEY (package_id, filepath)
                )
            """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_pkg ON events(package_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tags ON events(tags)")
        # search_blob 预筛可用性：仅看列是否存在（PRAGMA O(列数)，不扫行）；
        # 行级 NULL 由预筛 SQL 的 "OR search_blob IS NULL" 兜底，无需每查询全扫。
        _cols = {r[1] for r in c.execute("PRAGMA table_info(events)").fetchall()}
        self._blob_ok = "search_blob" in _cols

    def _blob_filter(self, terms, ql):
        """返回 (SQL片段, params)：search_blob 子串预筛（OR 各 term + ql）。

        命中行必含会被 _anchor_score 子串得分的锚点（超集）→ 只 parse+打分候选行，
        把 O(总锚点)/查询 降到 O(命中行锚点)，零召回回归。
        `OR search_blob IS NULL` 兜底旧行（未 rebuild 填充）→ 绝不静默丢召回。"""
        parts, params = [], []
        for t in terms:
            if t:
                parts.append("search_blob LIKE ?")
                params.append("%" + str(t).lower() + "%")
        if ql:
            parts.append("search_blob LIKE ?")
            params.append("%" + str(ql).lower() + "%")
        if not parts:
            return "", []
        return "(" + " OR ".join(parts) + " OR search_blob IS NULL)", params

    def _blob_populated(self):
        """懒判定 search_blob 是否已【全行填充】。

        仅首次调用跑一次 O(行数) 的 count(*)（NULL 行数），结果缓存到
        self._blob_populated，后续直接命中缓存（零额外开销）。

        - True  ：所有行已填充（正常 rebuild 后的库）→ 三处 corpus SQL 函数
                  （_corpus_blob_candidates / _entity_in_corpus / _rare_entities）
                  可安全走 LIKE 快速路径；NULL 行不存在，不会漏命中→误拒答。
        - False ：仍有 NULL 行（旧库未 rebuild_all，search_blob 全空）→ 三处
                  函数退回逐文件 body 扫描兜底，绝不因 LIKE 漏 NULL 行而假拒答。

        关键区分：_score 的 _blob_filter 用「OR search_blob IS NULL」已天然兜底
        旧行（NULL 行仍进候选池），无需此判定；本方法仅服务于 LIKE『命中』语义的
        三处 corpus 函数——它们的 NULL 行会被 LIKE 静默排除，必须显式降级。

        为何不直接依赖 _blob_ok：_blob_ok 只看列是否存在（旧库 ALTER 后也 True），
        但列存在 ≠ 行已填充。旧库未 rebuild 时列全 NULL，若只判 _blob_ok 会误走
        快速路径并假拒答——故必须独立判定填充度。
        """
        if self._blob_populated_cache is not None:
            return self._blob_populated_cache
        c = self._conn()
        n_null = c.execute(
            "SELECT count(*) FROM events WHERE search_blob IS NULL"
        ).fetchone()[0]
        self._blob_populated_cache = (n_null == 0)
        return self._blob_populated_cache

    # ---- 召回消歧：歧义门 + 特征判别澄清（实体歧义由本方法承担）-----------
    def _entity_feature_index(self, package_id=None):
        """构建实体特征索引 {ekey: {"features":{token:tier}, "title":..., "rids":[...]}}。

        复用生产四要素约定：person/topic/location 为 {canonical:[variants]} dict，
        anchors 为 [{Chapter, about, keywords}]；仅结构化维度计入判别特征，
        title/summary/about/chapter 等自由文本排除（粒度太粗会伪造独特性）。
        实体按 _entity_key(title) 去重，多行/多分章归并为一个实体。
        """
        c = self._conn()
        if package_id:
            rows = c.execute(
                "SELECT filepath,title,summary,tags,person,topic,location,anchors "
                "FROM events WHERE package_id=? OR package_id LIKE ? || '/%'",
                (package_id, package_id)).fetchall()
        else:
            rows = c.execute(
                "SELECT filepath,title,summary,tags,person,topic,location,anchors "
                "FROM events").fetchall()
        idx = {}
        for fp, title, summary, tags_j, pj, tj, lj, aj in rows:
            ek = _entity_key(title)
            ent = idx.setdefault(ek, {"features": {}, "title": title, "rids": []})
            ent["rids"].append(os.path.splitext(os.path.basename(fp))[0])
            feats = ent["features"]
            for raw, ftype in ((pj, "person"), (tj, "topic"), (lj, "location")):
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    parsed = None
                d = _as_four(parsed)
                tier = _FIELD_TIER.get(ftype, 0)
                for canon, variants in d.items():
                    for tok in ([canon] + list(variants or [])):
                        tk = _norm(tok)
                        if len(tk) >= 2 and (tk not in feats or tier > feats[tk]):
                            feats[tk] = tier
            try:
                for tg in json.loads(tags_j or "[]"):
                    tk = _norm(tg)
                    if len(tk) >= 2:
                        tier = _FIELD_TIER["tags"]
                        if tk not in feats or tier > feats[tk]:
                            feats[tk] = tier
            except Exception:
                pass
            try:
                for a in json.loads(aj or "[]"):
                    if not isinstance(a, dict):
                        continue
                    for kw in (a.get("keywords") or a.get("tags") or []):
                        tk = _norm(kw)
                        if len(tk) >= 2:
                            tier = _FIELD_TIER["kw"]
                            if tk not in feats or tier > feats[tk]:
                                feats[tk] = tier
            except Exception:
                pass
        return idx

    def _neg_features_from_query(self, q, idx):
        """从查询抽否定子句（「不是X」→ 排除带 X 特征的实体）。

        启发式：定位否定标记后的子句，从索引全部特征里挑出与子句双向子串相关的 token。
        生产环境应换 LLM 精准解析否定意图（同 resolve_query 管线可插拔）。"""
        _NEG_MARKERS = ("不是", "排除", "除了", "非", "别是", "不要", "而非")
        ql = _norm(q)
        for marker in _NEG_MARKERS:
            if marker in ql:
                clause = ql.split(marker, 1)[1]
                negs = set()
                for ent in idx.values():
                    for tok in ent["features"]:
                        if len(tok) >= 2 and (tok in clause or clause in tok):
                            negs.add(tok)
                return negs
        return set()

    def _anchor_only_tokens(self):
        """全局『仅出现在锚点 keywords、不在任何结构化字段(person/topic/location)』的 token 集。

        这些 token 是实体正文里顺带提到的共现词（如故事里出现的配角名 示例人物/弗瑞），
        不是该实体自身的判别特征。澄清『独有弧段』应排除它们，只亮实体自己的特征。
        结构化特征口径与 _entity_feature_index 一致：person/topic/location 的规范名 + 变体。"""
        c = self._conn()
        structured, anchor = set(), set()
        for fp, pj, tj, lj, aj in c.execute(
                "SELECT filepath, person, topic, location, anchors FROM events"):
            for raw in (pj, tj, lj):
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    parsed = None
                d = _as_four(parsed)
                for canon, variants in d.items():
                    for tok in ([canon] + list(variants or [])):
                        tk = _norm(tok)
                        if len(tk) >= 2:
                            structured.add(tk)
            try:
                for a in json.loads(aj or "[]"):
                    if not isinstance(a, dict):
                        continue
                    for kw in (a.get("keywords") or a.get("tags") or []):
                        tk = _norm(kw)
                        if len(tk) >= 2:
                            anchor.add(tk)
            except Exception:
                pass
        return anchor - structured

    # ---- 覆盖门（软·强信号快捷通道）---------------------------------------
    def _query_tokens(self, q, keywords=None, decomposer=None):
        """覆盖门用的查询 token：与召回同源。
        - keywords 来自理解层（AI 路径）→ 直接采用。
        - decomposer 注入 → 取其分解结果。
        - 否则按 '+'/空白 切分（AIMH 特征词查询形态：蓝+钻石 / 孤品 蓝钻）。
        不做 CJK 二元扩展：保持与沙箱原型一致的『连续子串』匹配语义，
        避免 '纯蓝' 误命中 '纯净蓝'（净在中间非连续）导致 paraphrase 被误判为区分词。
        """
        if keywords is not None:
            toks = [str(k).strip() for k in keywords if str(k).strip()]
        elif callable(decomposer):
            dq = decomposer(self, q) or ""
            toks = [t for t in re.split(r'[+\s]+', dq) if t]
        else:
            toks = [t for t in re.split(r'[+\s]+', q.strip()) if t]
        out, seen = [], set()
        for t in toks:
            tl = t.lower()
            if tl and tl not in seen:
                seen.add(tl)
                out.append(tl)
        return out

    # ---- 写入侧反推：落库完整性检查（检测缺独有弧段的实体）---------------
    def _missing_unique_arcs(self, idx, global_count, target_ekeys, soft_k=3):
        """检测缺乏独有弧段的实体（写入侧反推的核心计算）。

        判据（修正文档中 G(e) 的提法：严格独有弧 global_count==1 故 G(e) 恒为 1，
        软缺失改用『共有邻居数』share_count 衡量拥挤度）：
          · 实体无任何结构化特征（F(e)=∅）→ 跳过（惰性实体，非歧义风险）。
          · 硬缺失：F(e)≠∅ 且 unique_arcs（global_count==1）为空 → 全部特征被其他
            实体共享，任何命中它的查询必落多圆交集、必触发歧义门。
          · 软缺失：有独有弧但 share_count≥soft_k → 处于拥挤邻域，建议补更具体关键词。
        idx / global_count 必须由调用方基于『全局』实体特征索引构建（唯一性能否成立
        须相对全部实体判定，不能只在单包内看）。target_ekeys=None 评估全部实体。
        返回 [{ekey,title,severity,unique_arcs,share_count,suggest}]。
        """
        if target_ekeys is None:
            target_ekeys = set(idx.keys())
        warnings = []
        for ek in target_ekeys:
            if ek not in idx:
                continue
            F = idx[ek]["features"]
            if not F:
                continue  # 惰性实体：无结构化特征，非歧义风险，不误报
            unique = [f for f in F if global_count.get(f, 9999) == 1]
            # 共有邻居：与 e 共享≥1 特征的其它实体数（O(E·F)，个人记忆规模可忽略）
            co = 0
            Fset = set(F)
            for o, oent in idx.items():
                if o == ek:
                    continue
                if Fset & set(oent["features"]):
                    co += 1
            if not unique:
                severity = "hard"
            elif co >= soft_k:
                severity = "soft"
            else:
                continue
            reason = ("没有任何独有特征，召回极易与其它实体混淆"
                      if not unique else f"处于拥挤邻域（与 {co} 个实体共享特征）")
            suggest = (f"「{idx[ek]['title']}」{reason}；请给它一个别处用不到的独有关键词"
                       f"（某条独有属性 / 代号 / 场景），写入 person/location/topic 规范名变体"
                       f"或锚点 keywords，使其获得至少一条 global_count==1 的独有弧段。")
            warnings.append({
                "ekey": ek,
                "title": idx[ek]["title"],
                "severity": severity,
                "unique_arcs": unique,
                "share_count": co,
                "suggest": suggest,
            })
        return warnings

    def _build_idf(self):
        """懒构建文档频率表。

        文档 = 单个事件包「全部锚点的 title+summary+body+tags 拼成的一段」。
        df(t) = 含 t（子串）的包数；idf = log((N+1)/(df+1)) + 1，N 为包总数。
        该统计只读 index.db，可随时由 front-matter 重建，故不落盘缓存。
        """
        c = self._conn()
        docs = []
        for rid, aj in c.execute("SELECT filepath,anchors FROM events").fetchall():
            try:
                anchors = json.loads(aj or "[]")
            except Exception:
                anchors = []
            parts = []
            for a in anchors:
                if not isinstance(a, dict):
                    continue
                parts.append((a.get("title") or a.get("Chapter") or ""))
                parts.append((a.get("about") or a.get("summary") or ""))
                parts.append(self._anchor_body(rid, a))
                for tg in (a.get("tags") or a.get("keywords") or []):
                    parts.append(tg)
            docs.append(" ".join(parts).lower())
        self._idf_docs = docs
        self._idf_df = {}
        self._idf_N = len(docs)

    # ---- 确定性 BM25 重排（query_anchors 的 rerank=True 模式）---------------
    # 无向量、可由正文重建，对应 HMA 理解层/L2 的排序职责。
    # 实测把 hit@5 从 89.7% 提到 ~92%、hit@1 从 60% 提到 ~72%
    # （LoCoMo 1982 题，reform+idf+pkgagg 配置下）。
    _RERANK_TOK = re.compile(r"[A-Za-z0-9]+|[一-鿿]")
    _RERANK_K1 = C.RERANK_K1
    _RERANK_B = C.RERANK_B
    _RERANK_COV_W = C.RERANK_COV_W

    def _kw_index(self):
        """结构性关键词→包索引（关键词补齐用），从 DB 各包锚点 keywords 派生。

        非手写：随语料自动更新，新包进仓库即获得判别力。缓存于实例（rebuild
        后失效：调用方重新构造 Memory 即可）。返回 {keyword(lower): set(package_id)}。
        """
        if getattr(self, "_kw_index_cache", None) is None:
            idx: Dict[str, Set[str]] = {}
            c = self._conn()
            for pid, aj in c.execute("SELECT package_id, anchors FROM events"):
                try:
                    anchors = json.loads(aj or "[]")
                except Exception:
                    anchors = []
                for a in anchors:
                    if not isinstance(a, dict):
                        continue
                    for kw in (a.get("keywords") or []):
                        if kw:
                            idx.setdefault(str(kw).lower(), set()).add(pid)
            self._kw_index_cache = idx
        return self._kw_index_cache

    # ---- 拒答层（faithfulness gate，确定性、零 ML）---------------------------
    def _pkg_body(self, rid):
        """单包正文（小写），供 Gate1 覆盖度复用 _anchor_score 的实际打分字段。

        正文只存 .md（events 表无 body 列），故走 read_body 从文件取。
        """
        b = self.read_body(rid)
        return (b or "").lower()



    def _pkg_fields(self, rid, pid=None):
        """单包四要素字段集合（小写），供 Gate2 命中判定。

        rid 内部为文件名 stem（V2 检索契约）；filepath 列存完整路径，
        故按 stem 模糊匹配。pid 限定包作用域——query_anchors 已按包缩圈，
        必须沿用同一作用域，否则同名 stem（如 demo 包与正式包都叫
        demo-origin）会被跨包误判，导致正确实体被错拒。
        """
        c = self._conn()
        if rid.endswith(".md"):
            q = "SELECT person,location,topic,event_date FROM events WHERE filepath=?"
            params = (rid,)
        else:
            q = ("SELECT person,location,topic,event_date FROM events "
                 "WHERE (filepath LIKE ? OR filepath LIKE ?)")
            params = ("%/" + rid + ".md", "%\\" + rid + ".md")
        if pid:
            q += " AND package_id=?"
            params = params + (pid,)
        rows = c.execute(q, params).fetchall()
        if not rows:
            return set()
        s = set()
        for p, loc, top, d in rows:
            for fld in (p, loc, top):
                for v in _flat_variants(fld):
                    if v:
                        s.add(str(v).lower())
            if d:
                s.add(str(d).lower())
        return s

    def _out_of_scope(self, q, scored, pid=None):
        """Gate2：查询解析出已知四要素实体，但召回包「四要素 + 正文」零命中 → 越界拒答。

        忠实落地用户设计的「基准真机制=四要素字段缩圈」：当前 query_anchors
        只把四要素当 rerank 裁判（_apply_field_weights），从不缩圈；此闸让越界
        查询真正被拒。零 ML（对全库实体词表做字典命中）。未知实体（不在词表）
        则交 Gate1 覆盖度判定（即用户设计的「topic 未规范则缩圈静默漏」边界）。

        命中口径须与 _coverage/_anchor_score 一致（title+about+tags+body）：
        实体只要出现在召回包的正文里，即视为「在包内」，不被四要素硬闸误拒——
        否则会出现「body 命中、about 未命中」的正确召回被过度拒答
        （Demo 实测 5/9 过度拒答即此因；如代号「黑寡妇」仅在正文出现、
        未进结构化 person 变体时不应被错拒）。
        """
        vocab = self._entity_vocab()
        if not vocab:
            return False
        ql = str(q).lower()
        resolved = {e for e in vocab if e and e in ql}
        if not resolved:
            return False
        for rid in {s[0] for s in scored}:
            if self._pkg_fields(rid, pid) & resolved:
                return False
            # 正文命中同样算「在包内」（与 _coverage 同口径）
            body = self._pkg_body(rid)
            if body and any(e in body for e in resolved):
                return False
        return True

    def _corpus_files(self, pid=None):
        """作用域内全部 .md 的 filepath（与 query_anchors 同 scope）。

        pid 非空 → package_id=? OR package_id LIKE pid||'/%'；pid 空 → 全库。
        供 Gate1 语料包含性校验做全量正文扫描。
        """
        c = self._conn()
        if pid:
            rows = c.execute(
                "SELECT DISTINCT filepath FROM events "
                "WHERE package_id=? OR package_id LIKE ? || '/%'",
                (pid, pid)).fetchall()
        else:
            rows = c.execute("SELECT DISTINCT filepath FROM events").fetchall()
        return [r[0] for r in rows if r[0]]

    # 语料包含性拒答的「干净实体」过滤：剥离问句壳（疑问/功能字）与跨域通用词，
    # 只认能代表问题的专有实体/概念词。避免「作者/价格/怎么」等跨域词把域外问题
    # 误判为领域内（如「红楼梦的作者是谁」中"作者"在库却非实体 → 仍拒答）。
    _FUNCTIONAL_CHARS = set(
        "谁什么怎么怎样哪几多是的吗呢为何如何多少干嘛啥"
        "有系颗行阳太币格价今作"
    )
    _GENERIC_TERMS = {
        "作者", "价格", "做法", "意思", "定义", "名字", "时间", "地方", "类型",
        "方式", "原因", "作用", "内容", "方法", "过程", "问题", "情况", "事情",
        "东西", "部分", "为什么", "何处", "干嘛", "多少", "怎么",
        # 查询状态/时间副词：非内容实体，与「时间/情况」同类，从判别实体剔除，
        # 避免域外问题（量子计算/苹果股价）靠「最新/进展/股价」等通用碎片误判语料有。
        "最新", "进展", "新进", "股价", "目前", "当前", "更新", "近日", "近来",
        "此前", "当时", "如今", "关于", "方面",
    }

    # ---- 多跳召回：沿 linked 双向 BFS 扩簇（V1.0 生产化）-------------------
    def _linked_adjacency(self):
        """从 events.linked 建无向邻接表 {filepath: set(filepath)}。

        linked 存复合 id（如 `项目/AIMH-design-journal/xxx.md`，可能带/不带
        `memory/` 前缀，或仅写 stem）。解析时按「后缀匹配 filepath」兜底，
        解析不到的悬空 id 直接丢弃（不报错）。双向：link() 已双写，此处仍按
        边并集处理，兼容旧/部分 link。零 ML、可由 index.db 重建。
        """
        c = self._conn()
        rows = c.execute("SELECT filepath, linked FROM events").fetchall()
        fps = [fp for fp, _ in rows]
        fp_index = {fp.replace("\\", "/"): fp for fp in fps}

        def resolve(lid):
            if not lid:
                return None
            lid_n = lid.replace("\\", "/").lstrip("/")
            for key, fp in fp_index.items():      # 1) 后缀匹配（兼容 memory/ 前缀）
                if key.endswith("/" + lid_n) or key == lid_n:
                    return fp
            stem = os.path.splitext(os.path.basename(lid))[0]   # 2) stem 匹配
            for fp in fps:
                if os.path.splitext(os.path.basename(fp))[0] == stem:
                    return fp
            return None

        adj = {fp: set() for fp in fps}
        for fp, lj in rows:
            try:
                links = json.loads(lj or "[]") or []
            except Exception:
                links = []
            for lid in links:
                r = resolve(lid)
                if r and r != fp:
                    adj[fp].add(r)
                    adj[r].add(fp)                # 双向
        return adj



    # ---- 读取正文（冷存储按需取）------------------------------------------
    def read(self, id, package_id=None):
        """读取事件包正文（db-first 定位 filepath，支持跨包按 id 取）。

        id 入参兼容两种：文件名 stem（如 "demo-base"）或完整 filepath。
        package_id=None（默认）→ 用当前句柄作用域；传 "" → 全局取首个匹配；
        传具体包 id 则限定。索引缺失/路径失效时回退到当前包 events_dir 直读。
        """
        c = self._conn()
        pid = package_id if package_id is not None else self.package_id
        row = None
        if id.endswith(".md"):
            # 直接按完整 filepath 取
            row = c.execute(
                "SELECT filepath FROM events WHERE filepath=?",
                (id,)).fetchone()
        elif pid:
            row = c.execute(
                "SELECT filepath FROM events "
                "WHERE package_id=? AND REPLACE(filepath, '\\', '/') LIKE ?",
                (pid, "%/" + id + ".md")).fetchone()
        else:
            row = c.execute(
                "SELECT filepath FROM events WHERE REPLACE(filepath, '\\', '/') LIKE ? LIMIT 1",
                ("%/" + id + ".md",)).fetchone()
        path = row[0] if (row and row[0]) else None
        # P2-D：索引里的 filepath 若已被污染到树外（历史脏数据 / 外部改库），
        # 一律不采信——否则 db-first 会绕开下面的 _safe_md_path 直接读树外。
        if path and not _in_tree(path, self.events_dir):
            path = None
        if not path or not os.path.exists(path):
            try:
                path = _safe_md_path(self.events_dir, id)
            except ValueError:
                return None
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
            m = re.match(r"^(#{2,6})\s+(.*)$", ln)
            if m and heading in m.group(2):
                start, level = i, len(m.group(1))
                break
        if start is None:
            return None
        out = [lines[start]]
        for j in range(start + 1, len(lines)):
            m = re.match(r"^(#{2,6})\s+", lines[j])
            if m and len(m.group(1)) <= level:
                break
            out.append(lines[j])
        return "\n".join(out).strip()

    def _anchor_body(self, rid, anchor):
        """取锚点章节正文：优先内联 body，缺失时从磁盘按 Chapter 回源。

        SCHEMA 规定 anchors 不内联 body（body 为唯一内容源），故召回需要章节
        正文时走 read_section 同款「按标题切章」逻辑回源。整文件 body 按 rid
        缓存，避免全库检索时逐锚点重复磁盘 I/O（同文件只直读一次）。
        rid 兼容完整 filepath 或文件名 stem（交给 self.read 解析）。
        """
        if not isinstance(anchor, dict):
            return ""
        inline = anchor.get("body")
        if inline:
            return inline
        chapter = anchor.get("Chapter") or anchor.get("title")
        if not chapter or not rid:
            return ""
        cache = getattr(self, "_body_cache", None)
        if cache is None:
            cache = self._body_cache = {}
        if rid not in cache:
            try:
                pkg = self.read(rid)
                cache[rid] = (pkg.body if pkg else "") or ""
            except Exception:
                cache[rid] = ""
        body = cache[rid]
        if not body:
            return ""
        # 切片结果按 (rid, chapter) 缓存：同文件多次取同一章（_score 与 _apply_field_weights
        # 各取一次）不重复 splitlines + 扫描，进一步压低大库检索的 Python 侧开销。
        scache = getattr(self, "_body_slice_cache", None)
        if scache is None:
            scache = self._body_slice_cache = {}
        skey = (rid, chapter)
        if skey in scache:
            return scache[skey]
        lines = body.splitlines()
        start, level = None, None
        for i, ln in enumerate(lines):
            m = re.match(r"^(#{2,6})\s+(.*)$", ln)
            if m and chapter in m.group(2):
                start, level = i, len(m.group(1))
                break
        if start is None:
            scache[skey] = ""
            return ""
        out = [lines[start]]
        for j in range(start + 1, len(lines)):
            m = re.match(r"^(#{2,6})\s+", lines[j])
            if m and len(m.group(1)) <= level:
                break
            out.append(lines[j])
        result = "\n".join(out).strip()
        scache[skey] = result
        return result

    # ---- 不起眼物件 / 长尾细节召回（context-scope + 人机共审）---------------
    def obscure_recall(self, q, obj_token, package_id=None,
                       scope_chapter=None, scope_mode="reading",
                       top_k=5, window=200):
        """不起眼物件 / 长尾细节追问召回。

        针对「无锚点位、机械层选不出描述段」的长尾细节（如「示例角色在伊斯坦布尔
        那张唱片封面什么样」）：机械层只有局部倒排、无章级定位能力，故用交互状态
        提供的章级范围信号（context-scope）绕开死结，章内切片后走双路线：

          路线一（范围候选 · AI 自读理解）：把候选段集交 AI 在窄语境自读理解出答案。
          路线二（C+A 段卡片 · 人机共审）：每段以「C 章 + A 锚点 about + 段原文」
                卡片摊开，系统不单方出答案、终审权在人。

        路线一无果（候选集无真段 / 读不出确定答案）→ 自动拒答并强制降级转路线二。

        参数：
          q            : 用户原问句（仅审计/展示用，不参与机械匹配）
          obj_token    : 特征实体词（如「唱片」），章内局部倒排的检索词
          package_id   : 目标事件包复合 id（如 原创角色/示例角色/demo-origin）；
                         不传则全仓扫描（弱信号/无范围时）
          scope_chapter: 用户显式指明的章标题（强信号，直接锁章）；与 scope_mode 互斥
          scope_mode   : "explicit"(强·scope_chapter 锁章) / "reading"(弱·阅读位置缩圈+全包兜底)
                         / "global"(全包宽召回)
          top_k        : 返回候选段上限（安全闸）
          window       : 局部倒排切窗半径（字符数）

        返回 dict（与 query_anchors 的 allow_abstain 结构化返回风格一致）：
          {
            "route": "one" | "two",          # 最终走哪条路线
            "route_one_read": bool,          # 路线一是否读出了答案
            "scope": {...},                  # 实际锁定的章范围
            "cards": [ {chapter, about, segment, near}, ... ],  # 路线二 C+A 段卡片
            "auto_abstain": bool,            # 路线一无果自动拒答标记
            "message": str,                  # 人类可读摘要
          }
        """
        # ── 0. 取目标包正文 + 真实锚点 ──────────────────────────────────
        if package_id:
            pkg = self.read(package_id)
            bodies = [(package_id, pkg.body)] if pkg else []
        else:
            bodies = []
            for rid in self.list_all_in_scope(top_k=None):
                p = self.read(rid)
                if p and p.body:
                    bodies.append((rid, p.body))
        if not bodies:
            return {"route": "two", "route_one_read": False, "scope": {},
                    "cards": [], "auto_abstain": True,
                    "message": "(ABSTAIN: 无目标包) 记忆中无匹配，请勿编造"}

        # ── 1. 章级切分 + 锚点映射（每个包独立处理，合并候选）──────────────
        all_chapters = []   # [(pkg_id, chapter_title, chapter_body, anchor_about)]
        for rid, body in bodies:
            chapters = ro.split_chapters(body)
            anchors = derive_anchors(body, max_level=6)
            amap = {a["Chapter"]: a.get("about", "") for a in anchors}
            for ctitle, cbody in chapters:
                all_chapters.append((rid, ctitle, cbody, amap.get(ctitle, "")))

        # ── 2. context-scope 锁章（三级范围信号）─────────────────────────
        if scope_mode == "explicit" and scope_chapter:
            scope_chapters = [(r, t, b, a) for (r, t, b, a) in all_chapters
                              if scope_chapter in t]
            scope_label = f"显式锁章：{scope_chapter}"
        elif scope_mode == "reading":
            # 弱信号：阅读位置缩圈到 top3 候选章（按 obj_token 命中数降序）+ 全包兜底
            scored = sorted(all_chapters,
                            key=lambda x: x[2].count(obj_token), reverse=True)
            scope_chapters = scored[:3]
            scope_label = "阅读位置缩圈(top3章)+全包兜底"
        else:
            scope_chapters = all_chapters
            scope_label = "全包宽召回"

        # ── 3. 章内局部倒排 + 重叠合并瘦身 ───────────────────────────────
        cands = []   # [(pkg_id, chapter_title, about, segment, near)]
        raw_intervals = []  # [(pkg_id, title, about, start, end, near)]
        for rid, ctitle, cbody, about in scope_chapters:
            for pos in ro.local_inverted(cbody, obj_token):
                s = max(0, pos - window)
                e = min(len(cbody), pos + len(obj_token) + window)
                raw_intervals.append((rid, ctitle, about, s, e, True))
        # 重叠合并瘦身（机械层去冗余，不替 AI 选段）
        merged = ro.slim_segments(raw_intervals)
        for rid, ctitle, about, s, e, near in merged:
            pkg = self.read(rid)
            cbody = pkg.body if pkg else ""
            seg = ro.chapter_slice(cbody, ctitle, s, e)
            cands.append((rid, ctitle, about, seg, near))

        if not cands:
            return {"route": "two", "route_one_read": False,
                    "scope": {"label": scope_label}, "cards": [],
                    "auto_abstain": True,
                    "message": "(ABSTAIN: 候选集为空) 记忆中无匹配，请勿编造"}

        # ── 4. 路线一：AI 自读判定（确定性模拟——沙箱同款判定）────────────
        # 判定：候选段同窗含 obj_token 且 about 真正涉及 obj_token 概念 → 读出
        # 生产侧这里留 decomposer 注入口；不传则走确定性占位判定（必然保守无果）
        route_one_read = False
        for rid, ctitle, about, seg, near in cands:
            if near and obj_token in (about or ""):
                route_one_read = True
                break

        # ── 5. 路线一无果 → 自动拒答 + 强制降级转路线二 ──────────────────
        if not route_one_read:
            cards = [{"chapter": t, "about": a, "segment": seg, "near": near}
                     for (_, t, a, seg, near) in cands[:top_k]]
            return {"route": "two", "route_one_read": False,
                    "scope": {"label": scope_label},
                    "cards": cards, "auto_abstain": True,
                    "message": ("(路线一无果·自动拒答) 候选集未含描述段，已转路线二 "
                                "C+A 段卡片交人终审；系统不单方出答案")}

        # ── 6. 路线一读出：返回候选段（AI 自读上下文）────────────────────
        cards = [{"chapter": t, "about": a, "segment": seg, "near": near}
                 for (_, t, a, seg, near) in cands[:top_k]]
        return {"route": "one", "route_one_read": True,
                "scope": {"label": scope_label}, "cards": cards,
                "auto_abstain": False,
                "message": "(路线一·AI 自读) 候选段已交理解层，precision 由 AI 在窄语境承担"}

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
                pkg = _load_for_index(path)
                if pkg is None or not pkg.id:
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
        count = 0
        repo = self.repo
        # 整库重建包成单个事务：1000 次 upsert 合并为 1 次提交，
        # 避免 autocommit（isolation_level=None）下每 INSERT 一次 fsync 的开销。
        # 事务内持有写锁，MCP 并发读会短暂阻塞——rebuild 是维护操作可接受；
        # 且原子提交保证"要么全建好、要么回到重建前"，比逐条提交更安全。
        if c.in_transaction:
            c.execute("ROLLBACK")
        c.execute("BEGIN IMMEDIATE")
        try:
            c.execute("DELETE FROM events")   # 清库，再逐包重建（同事务内）
            if progress:
                progress("scan", "开始全量重建索引（清除旧索引后逐包重扫）…")
            for dirpath, dirnames, filenames in os.walk(repo):
                # 跳过派生缓存：根级 目录结构树.md 自带 id front-matter，
                # 若纳入会被误索成 package_id='' 的游离根行
                if "目录结构树.md" in filenames:
                    filenames.remove("目录结构树.md")
                # R50：一个"包"= 直接含可解析事件 .md 的目录
                # （不再要求 events/ 子目录；命名空间目录自身不含 .md → 不会误判）
                md_events = []
                for fn in filenames:
                    if not fn.endswith(".md") or fn.endswith(".tmp"):
                        continue
                    _p = os.path.join(dirpath, fn)
                    if not os.path.isfile(_p):
                        continue
                    # 脚本派生视图由 _load_for_index 内部判标记跳过；这里仅收集候选路径
                    md_events.append(_p)
                if not md_events:
                    continue
                pkg_dir = dirpath
                pid = _pkg_id(pkg_dir, repo)
                if progress:
                    progress("pkg", "%s  (%d 事件)" % (pid or "(仓库根)", len(md_events)))
                for _p in md_events:
                    pkg = _load_for_index(_p)
                    if pkg is None or not pkg.id:
                        continue
                    self._upsert(pkg, _p, package_id=pid)
                    count += 1
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
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
            pkg = _load_for_index(path)
            if pkg is None or not pkg.id:
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
            # P2-D 同源：rmtree 前必须确认落点在仓库树内且不是仓库根本身
            if not _in_tree(target, self.repo) or os.path.abspath(target) == os.path.abspath(self.repo):
                raise ValueError(f"package_id 越出仓库树或指向仓库根：拒绝删除（{package_id!r}）")
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
        return package_id

    # ---- 工具 -----------------------------------------------------------------
    def list_all(self):
        c = self._conn()
        if self.package_id:
            rows = c.execute(
                "SELECT filepath,title,tags,pkage_updated FROM events "
                "WHERE package_id=? ORDER BY pkage_updated DESC, filepath",
                (self.package_id,)).fetchall()
        else:
            rows = c.execute(
                "SELECT filepath,title,tags,pkage_updated FROM events "
                "ORDER BY pkage_updated DESC, filepath").fetchall()
        return [(os.path.splitext(os.path.basename(r[0]))[0], r[1] or "",
                 r[2] or "", r[3] or "") for r in rows]

    def orchestrate(self, sub_queries, top_k=5, keywords=None, scope=None,
                    allow_abstain=True):
        """multi 模式扇出-合并：AI 已拆好 sub_queries 清单，引擎确定性循环 query_anchors
        各子问并按子问分组返回。不内置拆问（拆问归 AI 理解层，CEMA）。

        返回 [(sub_q, hits, reason_or_None), ...]，hits 为
        [(pkg_id, anchor_title, anchor_about, locator, score), ...]；
        reason 非空表示该子问被拒答（allow_abstain 触发）。跨子问按 (pkg_id, anchor_title)
        去重，避免多子问命中同锚点重复罗列。
        """
        out = []
        seen = set()
        for sq in (sub_queries or []):
            sq = str(sq).strip()
            if not sq:
                continue
            hits = self.query_anchors(
                sq, top_k=top_k, package_id=None, dedup_packages=False,
                use_field_weights=True, allow_abstain=allow_abstain,
                keywords=keywords, scope=scope)
            if isinstance(hits, dict):           # allow_abstain=True 结构化返回
                if hits.get("abstain"):
                    out.append((sq, [], hits.get("reason")))
                    continue
                hits = hits["answer"]
            deduped = []
            for (pkg_id, a_title, a_summary, locator, score) in hits:
                key = (pkg_id, a_title)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append((pkg_id, a_title, a_summary, locator, score))
            out.append((sq, deduped, None))
        return out

    def list_all_in_scope(self, scope=None, top_k=None):
        """枚举模式（QueryEnvelope mode=enumerate）的专用返回形态：列出 scope 子树内的
        全部包（确定性 filepath 排序，非 Top-K 相关度），供「该范围内都有什么」类枚举问。
        零-ML；scope=None 退化为全仓 list。"""
        c = self._conn()
        scl, spar = _scope_clause(scope, self.root)
        sql = "SELECT filepath,title,summary FROM events"
        params = []
        if scl:
            sql += " WHERE " + scl
            params += spar
        sql += " ORDER BY filepath"
        if top_k:
            sql += " LIMIT ?"
            params.append(int(top_k))
        rows = c.execute(sql, params).fetchall()
        out = []
        for fp, title, summary in rows:
            rid = fp
            if self.root and rid.startswith(self.root):
                rid = rid[len(self.root):]
            rid = rid.strip("/\\").removesuffix(".md")
            out.append((rid, title or "", summary or ""))
        return out

    def list_summaries(self):
        """(id, title, summary) 列表，仅供关联发现等内部用途，仅扫索引。
        当前包作用域（repo 级句柄 package_id="" 则全局）。"""
        c = self._conn()
        if self.package_id:
            rows = c.execute(
                "SELECT filepath,title,summary FROM events "
                "WHERE package_id=? ORDER BY pkage_updated DESC, filepath",
                (self.package_id,)).fetchall()
        else:
            rows = c.execute(
                "SELECT filepath,title,summary FROM events "
                "ORDER BY pkage_updated DESC, filepath").fetchall()
        return [(os.path.splitext(os.path.basename(r[0]))[0], r[1] or "",
                 r[2] or "") for r in rows]

    # ---- Type 8 计数（db_aggregate 结构化计数，零 raw-SQL 透传）--------------
    def aggregate(self, unit, filters=None, scope=None, return_list=False,
                   top_k=500):
        """Type 8（计数问）的结构化计数器：在 index.db 上做确定性 COUNT / 枚举。

        是对外（MCP memory_aggregate）的唯一计数入口；结构化入参、绝不透传 raw
        SQL。7 道护栏（SELECT-ONLY / 列白名单 / 值参数化 / 实体列走 json_each /
        只读连接 / 行数上限 500 / 显式 scope）见模块函数 db_aggregate。"""
        return db_aggregate(self.db_path, unit, filters=filters, scope=scope,
                            return_list=return_list, top_k=top_k, root=self.repo)

    # ---- Type 6 硬时间过滤（time_filter 结构化硬过滤，零 raw-SQL 透传）------
    def filter_by_time(self, time_hint, scope=None, top_k=500):
        """Type 6 硬时间过滤：自然语言时间意图 → 硬留 event_date 命中月份（含年）的包。

        是 memory_time_filter MCP 工具的后端；结构化入参、绝不透传 raw SQL；
        复用生产 parse_time_hint + 只读连接。返回匹配包 package_id 列表。"""
        return time_filter(self.db_path, time_hint, scope=scope,
                           root=self.repo, top_k=top_k)


# ---------------------------------------------------------------------------
# 锚点派生（确定性、OC 无关，纯 stdlib；供 EXE 打包安全复用）
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Type 8 计数（db_aggregate）：结构化变量 SQL 计数器
# ---------------------------------------------------------------------------
# 7 道护栏（对外 memory_aggregate MCP 工具的唯一计数后端，绝不透传 raw SQL）：
#   1) SELECT-ONLY：本函数自行拼 SQL，不接受任何外部 SQL 字符串
#   2) 列白名单：filters 的列与计数列仅限白名单，杜绝任意列读取
#   3) 值参数化：所有过滤值经 ? 占位，零字符串拼接（防 SQL 注入）
#   4) 实体列走 json_each：person/location/topic 是 {规范名:[变体]}，计数取 key
#   5) 只读连接：file:<db>?mode=ro，绝不写库
#   6) 行数上限：return_list 模式 LIMIT 500 硬上限
#   7) 显式 scope：scope 显式传入收束候选（None=全仓，零回归）


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


# 标题行：`#`~`######`，捕获层级与标题文本（兼容行尾 `#` 闭包）
_anchor_heading_re = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
# 句末切分（中英文句号/问叹/分号）
_anchor_sent_split = re.compile(r"(?<=[。！？!?；;\.])\s*")
# 表格分隔行（如 `| --- | --- |`）
_anchor_table_sep = re.compile(r"^[\s|:\-|]+$")


def derive_anchors(md_text, max_level=6):
    """从 Markdown 正文派生章级锚点列表。

    返回 [{Chapter, about, keywords}, ...]（v2 锚点 schema：无 locator/tags/body；
    body 为唯一内容源，anchors 仅关键词/梗概、不内联 body，召回时按需 read_section 回源）。
    默认 max_level=6：取 `##`~`######` 全层级（写入侧细切，读取侧成本最小化；
    章节层级过细导致内容被切断属原文文档本身结构问题，非检索侧责任）。
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
            "Chapter": title,
            "about": _anchor_first_sentence(body),
            "keywords": [],
        })
    return anchors


if __name__ == "__main__":
    import tempfile
    d = tempfile.mkdtemp()
    m = Memory(os.path.join(d, ".memory"))
    m.write("proj-x", "X 项目", "架构决策", ["x架构"], ["project", "decision"],
            body="# X\n初始综述")
    print("query 'x架构':", m.query("x架构"))
    print("rebuild ->", m.rebuild())
    print("query after rebuild:", m.query("架构"))
