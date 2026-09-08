# -*- coding: utf-8 -*-
"""event_package —— EventPackage 事件包数据类（S2 拆分自 hma_core）。

from_markdown / to_markdown（round-trip 序列化）、写回门禁（assert_writable /
mark_as_complete）与 FM 解析别名绑定；FM 解析实现在 hma/fm_yaml.py。
四要素兼容层（_as_four / _merge_legacy / _four_to_list）随类同迁——它们只被
本类与 Memory.write 消费，Memory 侧经 hma_core 的 re-export 引用，外部
（scripts/lint_memory 等）的 from hma.hma_core import … 零改动。
"""

import json
import os
from datetime import date

from . import fm_yaml
from .. import scoring_coeffs as C


# ---------------------------------------------------------------------------
# V2 四要素字段辅助（person / location / topic 一律为 {canonical:[variants]} 字典）
# ---------------------------------------------------------------------------
def _as_four(val):
    """四要素字段归一：None→{}；list[名称]→{名称:[]}；list[dict]→合并为 dict；
    dict 原样（值规整为列表）。

    兼容 V2 规范文件格式 [{规范名:[变体]}, …]（首级 list、每项单键 dict）——
    此前只认 list[str] 与 dict，遇 list[dict] 会触发 unhashable 崩溃。
    """
    if val is None:
        return {}
    if isinstance(val, dict):
        return {k: (list(v) if v else []) for k, v in val.items()}
    if isinstance(val, list):
        out = {}
        for item in val:
            if isinstance(item, dict):
                for k, vs in item.items():
                    out.setdefault(k, [])
                    for v in (vs or []):
                        if v not in out[k]:
                            out[k].append(v)
            elif item:
                out[item] = []
        return out
    return {}


def _merge_legacy(person, aliases, features):
    """把遗留 aliases(列表)/features({canon:[变体]}) 折叠进 person dict（V2 无独立列）。

    迁移保底：旧格式 .md（含 aliases/features 行、person 为列表）经此并入四要素
    字典，rebuild 后旧数据不丢、落到 V2 字段族。
    """
    d = _as_four(person)
    for a in (aliases or []):
        if a in d:                      # 已是某规范名，跳过（不把规范名当变体）
            continue
        if d:
            first = next(iter(d))
            if a not in d[first]:
                d[first].append(a)
        else:
            d[a] = []
    for canon, vs in (features or {}).items():
        d.setdefault(canon, [])
        for v in (vs or []):
            if v not in d[canon]:
                d[canon].append(v)
    return d


def _four_to_list(val):
    """合并 dict 形式的四要素 → 规范 front-matter 列表形式 [{规范名:[变体]}, …]。

    每项规定名拆成独立单键 dict（符合用户拍板的 [{规范名:[变体]}] 首级 [ ] 形态），
    供 to_markdown 序列化；若入参已是 list（含 list[dict] / list[str]）则规整后原样返回。
    """
    if isinstance(val, dict):
        return [{k: (list(v) if v else [])} for k, v in val.items()]
    if isinstance(val, list):
        out = []
        for item in val:
            if isinstance(item, dict):
                out.append({k: (list(v) if v else []) for k, v in item.items()})
            elif item:
                out.append({item: []})
        return out
    return val






def _derive_anchors_late(md_text, max_level=6):
    """运行时解析 hma_core.derive_anchors（S2 拆分后锚点派生仍居 hma_core 尾部，
    模块 import 期尚不存在，故延迟到调用期解析，避免循环 import）。"""
    from .. import hma_core
    return hma_core.derive_anchors(md_text, max_level)


class EventPackage:
    """一个事件包：YAML front-matter + Markdown 正文。"""

    def __init__(self, id="", title="", summary="", aliases=None, tags=None,
                 linked=None, created=None, updated=None, body="", anchors=None,
                 person=None, location=None, topic=None, event_date=None,
                 features=None, path=None):
        self.id = id                      # 文件名 stem（内存标识，非存储列）
        self.title = title
        self.summary = summary
        # 兼容旧调用：aliases / features 仅作临时入参，最终并入四要素 dict
        self._aliases_hint = list(aliases) if aliases else None
        self._features_hint = features or None
        self.tags = tags or []
        self.linked = linked or []
        self.created = created or str(date.today())   # 内存名；DB 列 = pkage_created
        self.updated = updated or str(date.today())   # 内存名；DB 列 = pkage_updated
        self.body = body
        self.anchors = anchors or []
        # 四要素（V2 一等字段）：一律 {canonical:[variants]} 字典；兼容旧 list
        self.person = _as_four(person)
        self.location = _as_four(location)
        self.topic = _as_four(topic)
        self.event_date = event_date or ""
        # 来源路径（读取时回填；非 front-matter 字段，不参与序列化）。
        self.path = path
        # —— 写回状态锁（合并门禁方案 2026-08-23）——
        # 默认残缺：直接构造的包必须显式 mark_as_complete() 洗白或经编排者
        # 降级解锁后，to_markdown / assert_writable 才放行。
        # 只有 from_markdown（全量读）会置 False；from_markdown_fm_only 置 True 并烙印。
        self._is_partial = True
        self._fm_only_read = False

    @property
    def aliases(self):
        """派生：四要素所有规范名 + 变体（V2 不再有独立 aliases 列）。"""
        out = list(self._aliases_hint) if self._aliases_hint else []
        for d in (self.person, self.topic, self.location):
            for k, vs in (d or {}).items():
                out.append(k)
                out.extend(vs or [])
        seen, res = set(), []
        for x in out:
            if x not in seen:
                seen.add(x)
                res.append(x)
        return res

    @property
    def features(self):
        """派生：{canonical:[变体]}（V2 不再有独立 features 列，由四要素推导）。"""
        out = dict(self._features_hint or {})
        for d in (self.person, self.topic, self.location):
            for k, vs in (d or {}).items():
                out.setdefault(k, [])
                for v in (vs or []):
                    if v not in out[k]:
                        out[k].append(v)
        return out

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

    def _fmt_anchors_block(self):
        """anchors 多行 block 输出（v3：每锚点 3 行，Chapter/about/keywords 各占一行；
        keywords 为单行内联 JSON 列表，不逐条分行）。

        对齐 _parse_fm 的 block 换行式路径：
          anchors:
            - Chapter: "<json>"
              about: "<json>"
              keywords: ["<json>", "<json>"]
        解析侧由 _parse_seq/_parse_mapping 无损还原，索引加载(from_markdown_fm_only)
        与全量读取(from_markdown) 共用 _parse_fm，故 rebuild 后 keywords 不丢。
        """
        if not self.anchors:
            return []
        out = ["anchors:"]
        for a in self.anchors:
            ch = json.dumps(a.get("Chapter", ""), ensure_ascii=False)
            about = json.dumps(a.get("about", ""), ensure_ascii=False)
            kws = a.get("keywords") or []
            out.append(f"  - Chapter: {ch}")
            out.append(f"    about: {about}")
            out.append(f"    keywords: {json.dumps(kws, ensure_ascii=False)}")
        return out

    def to_markdown(self):
        """
        纯序列化器（合并门禁方案 2026-08-23）。
        无放行参数、无深度校验。仅查状态锁 _is_partial：残缺包拒绝序列化。
        深度校验（body/anchors/keywords/覆盖保护）统一由 Memory.write 侧
        assert_writable() 负责，避免双校验漂移。
        """
        if getattr(self, '_is_partial', True):
            raise ValueError(
                "to_markdown() 拒绝序列化：本包处于残缺状态(_is_partial=True)。\n"
                "这通常因为：1. 由 from_markdown_fm_only 读出未补全；2. 新建包未洗白。\n"
                "若确已补全 body 和 anchors，请显式调用 pkg.mark_as_complete() 洗白，"
                "或经 Memory.write（自动洗白/降级解锁）写回。"
            )
        fm = [
            "---",
            f"title: {self.title}",
            f"summary: {self.summary}",
            f"tags: {self._fmt_list(self.tags)}",
            f"linked: {self._fmt_list(self.linked)}",
            # 四要素固定顺序输出（与用户拍板的字段顺序一致）；空字段也保留为 []，
            # 避免程序化写回时丢失字段、破坏「title→…→location→topic→…」固定顺序契约。
            f"person: {json.dumps(_four_to_list(self.person), ensure_ascii=False)}",
            f"event_date: {self.event_date or '—'}",
            f"location: {json.dumps(_four_to_list(self.location), ensure_ascii=False)}",
            f"topic: {json.dumps(_four_to_list(self.topic), ensure_ascii=False)}",
            *self._fmt_anchors_block(),
            f"pkage_created: {self.created}",
            f"pkage_updated: {self.updated}",
            "---",
            "",
            self.body if self.body.endswith("\n") else self.body + "\n",
        ]
        return "\n".join(fm)

    # ---- 写回门禁（合并门禁方案 2026-08-23）------------------------------
    def mark_as_complete(self):
        """显式洗白：新建包或全量修改包在落盘前必须盖章。
        fm_only 读出的包永远不可洗白（来源硬拦）。"""
        # 来源硬拦：from_markdown_fm_only 读出的包不可洗白
        if getattr(self, '_fm_only_read', False):
            raise ValueError(
                "洗白失败：本包由 from_markdown_fm_only 读出，永远不可洗白。"
                "若要修改并写回，必须使用 from_markdown 全量读取。"
            )
        if not (self.body or "").strip():
            raise ValueError("洗白失败：body 为空，禁止 mark_as_complete")
        if not self.anchors:
            raise ValueError("洗白失败：anchors 为空，禁止 mark_as_complete")
        # 深度校验：防空壳锚点（keywords 为空）骗过洗白导致索引黑洞
        for a in self.anchors:
            if not (a.get("keywords") or []):
                raise ValueError(
                    f"洗白失败：检测到空壳锚点（{a.get('Chapter', '?')}），keywords 为空。"
                )
        self._is_partial = False

    def assert_writable(self, existing_body="", allow_empty_body=False):
        """唯一写回门禁：合并状态锁 + 结构完整性 + 覆盖保护(R-safety)。
        Memory.write 在调 to_markdown 前必须调用。
        allow_empty_body=True（force 模式）：跳过 body 非空与覆盖保护，
        但仍查 _is_partial 状态锁与 anchors + keywords。"""
        if getattr(self, '_is_partial', True):
            raise ValueError("写回被拒：包处于残缺状态(_is_partial=True)，请先 mark_as_complete() 或显式降级解锁。")
        # allow_empty_body=True 时跳过 body 非空 + 覆盖保护（force 清空路径）
        if not allow_empty_body:
            if not (self.body or "").strip():
                raise ValueError("写回被拒：body 为空。")
            if (existing_body or "").strip() and not (self.body or "").strip():
                raise ValueError("写回被拒：现有正文非空，本次 body 为空（覆盖保护）。")
        # 无论是否 allow_empty_body，anchors 必查（索引来源不可空）；
        # keywords 不查（derive_anchors 派生的空 keywords 是系统常态，非空检查
        # 由 mark_as_complete 公开 API 负责，防 AI 显式补 kw 时空壳）。
        if not self.anchors:
            raise ValueError("写回被拒：anchors 为空。")

    # ---- 反序列化（读 .md）----------------------------------------------
    @classmethod
    def from_markdown(cls, text, filepath=None):
        # front-matter 必须用「独立行 ---」作边界（首尾各一个），
        # 不能用 text.split("---") —— 正文 / 内联锚点 body 里常含字面
        # `---`（如本规格文档），按子串切会把 front-matter 拦腰截断，
        # 导致 anchors 被误读成字符串并二次 JSON 编码污染索引。
        if not text.lstrip().startswith("---"):
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body=text.strip())
        lines = text.splitlines()
        if lines[0].strip() != "---":
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body=text.strip())
        # 找下一条「独立 --- 行」作为 front-matter 结束符
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body=text.strip())
        fm_text = "\n".join(lines[1:end])
        body = "\n".join(lines[end + 1:]).lstrip("\n")
        fm = cls._parse_fm(fm_text)
        # 若 front-matter 里的 anchors JSON 因含换行被解析器误读为空，
        # 则改从 body 重新派生（锚点本就完全可由正文还原）。
        anchors = fm.get("anchors", [])
        if not anchors and body.strip():
            anchors = _derive_anchors_late(body)
        # V2：id 由文件路径派生（不再有 id 列）；遗留 aliases/features 折叠进四要素 dict。
        person = _merge_legacy(fm.get("person"), fm.get("aliases"), fm.get("features"))
        pkg = cls(
            id=os.path.splitext(os.path.basename(filepath or "unknown"))[0],
            title=fm.get("title", ""),
            summary=fm.get("summary", ""),
            tags=fm.get("tags", []),
            linked=fm.get("linked", []),
            person=person,
            location=_as_four(fm.get("location")),
            topic=_as_four(fm.get("topic")),
            event_date=fm.get("event_date", ""),
            anchors=anchors,
            created=fm.get("pkage_created") or fm.get("created", ""),
            updated=fm.get("pkage_updated") or fm.get("updated", ""),
            body=body.strip(),
        )
        # 全量读出：状态完整可信，解除残缺锁
        pkg._is_partial = False
        pkg._fm_only_read = False
        return pkg

    @classmethod
    def from_markdown_fm_only(cls, text, filepath=None):
        """仅解析 front-matter 的轻量版，专供索引构建（rebuild / install）。

        索引不存正文（_upsert 不含 body 列），且 anchors 已随写入固化进
        front-matter，故跳过正文解析即可。返回 pkg；若 FM 缺 anchors（legacy
        包）则 anchors=[]，由调用方决定回退全量解析。
        """
        if not text.lstrip().startswith("---"):
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body="")
        lines = text.splitlines()
        if lines[0].strip() != "---":
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, body="")
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            # FM 被截断（head 太小）或无结束符：交给调用方回退全量解析
            fid = os.path.splitext(os.path.basename(filepath or "unknown"))[0]
            return cls(id=fid, title=fid, anchors=[], body="")
        fm_text = "\n".join(lines[1:end])
        fm = cls._parse_fm(fm_text)
        person = _merge_legacy(fm.get("person"), fm.get("aliases"), fm.get("features"))
        pkg = cls(
            id=os.path.splitext(os.path.basename(filepath or "unknown"))[0],
            title=fm.get("title", ""),
            summary=fm.get("summary", ""),
            tags=fm.get("tags", []),
            linked=fm.get("linked", []),
            person=person,
            location=_as_four(fm.get("location")),
            topic=_as_four(fm.get("topic")),
            event_date=fm.get("event_date", ""),
            anchors=fm.get("anchors", []),
            created=fm.get("pkage_created") or fm.get("created", ""),
            updated=fm.get("pkage_updated") or fm.get("updated", ""),
            body="",
        )
        # fm_only 读出：永远残缺、永远不可洗白（合并门禁方案 2026-08-23）
        pkg._is_partial = True
        pkg._fm_only_read = True
        return pkg

    # ---- FM/YAML 解析（S1 拆分：实现收编至 hma/fm_yaml.py，此处仅别名绑定）----
    # 保留原名 staticmethod 绑定：EventPackage._parse_fm 等调用点零改动，
    # 解析行为由 regress_fm_yaml（6 例护栏）+ 全量回归 + FM 基线快照比对把守。
    _strip_comment = staticmethod(fm_yaml.strip_comment)
    _scalar_or_json = staticmethod(fm_yaml.scalar_or_json)
    _parse_value = staticmethod(fm_yaml.parse_value)
    _parse_inline = staticmethod(fm_yaml.parse_inline)
    _is_kv = staticmethod(fm_yaml.is_kv)
    _empty_default = staticmethod(fm_yaml.empty_default)
    _parse_seq = staticmethod(fm_yaml.parse_seq)
    _parse_mapping = staticmethod(fm_yaml.parse_mapping)
    _parse_node = staticmethod(fm_yaml.parse_node)
    _normalize_anchor_kws = staticmethod(fm_yaml.normalize_anchor_kws)
    _parse_fm = staticmethod(fm_yaml.parse_fm)
