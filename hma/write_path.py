# -*- coding: utf-8 -*-
"""write_path —— 写入线（S5 拆分自 hma_core）。

WriteMixin 四方法 + 完整性体检：write（原子落盘 + 唯一门禁）、_upsert
（V2 索引 upsert）、_write_back（跨包 link 写回原目录，R58）、link（双向关联）、
check_write_integrity（写侧反推缺弧体检，integrity_check=True 时启用）。
路径护栏 _in_tree / _safe_md_path（P2-D：id 不得越出 memory 树，fail-closed）
语义上属于写入线，随迁至此；Memory.read 经 hma_core re-export 引用。

留守 hma_core 的跨线共享名（本模块运行时延迟解析，避免循环 import）：
_entity_key / _search_blob / derive_anchors / Memory。
EventPackage 与四要素兼容层在 hma/event_package.py。
"""

import json
import os
import re
from datetime import date

from .event_package import EventPackage, _merge_legacy


# ==================== 路径护栏（P2-D：写侧/读侧不得越出记忆树）====================
# 背景：Memory.write / read 曾直接 os.path.join(events_dir, f"{id}.md")，而 id 由
# MCP 入参透传（memory_write 的 id 字段）。id 含 `../` 即可读写 memory 树外，
# 绝对路径 id 更直接——os.path.join 遇绝对路径会丢弃左侧，连目录都不用跳——
# 可落到文件系统任意位置，并把树外 filepath 污染进 index.db。
# 护栏回归：AIMH-devkit/tests/regress_write_path_guard.py（红基线 1/8，修复后 8/8）。

def _in_tree(path, root):
    """path 是否在 root 树内。abspath 归一后按 root+sep 前缀比对。

    加 os.sep 是为了防「同前缀不同目录」钻空子：root=/a/memory 时，
    /a/memoryevil 不能以 startswith 蒙混过关。
    """
    p = os.path.abspath(path)
    r = os.path.abspath(root)
    return p == r or p.startswith(r + os.sep)


def _safe_md_path(events_dir, id):
    """id → 树内 .md 绝对路径；越界/绝对/空/异常一律 ValueError（fail-closed）。

    id 语义：相对 events_dir 的复合路径，不含 .md 后缀，用 / 分隔（可含中文）。
    """
    if not id or not isinstance(id, str):
        raise ValueError("id 必须是非空字符串")
    # 归一而不是禁止：Windows 侧引擎内部大量用 \ 分隔（list_all_in_scope 返回的
    # 就是 `人物\雪莱（诗人）\shelley-poet` 形态），禁反斜杠会把全部既有事件判非法。
    # 归一成 / 后，`..\outside\x` 与 `../outside/x` 同样由下面的树内校验拦下。
    norm = id.replace("\\", "/")
    if os.path.isabs(id) or os.path.isabs(norm) or re.match(r"^[A-Za-z]:", norm):
        raise ValueError(f"id 不得为绝对路径 / 盘符 / UNC（收到 {id!r}）")
    if norm.startswith("/"):
        raise ValueError(f"id 不得以 / 开头（收到 {id!r}）")
    p = os.path.abspath(os.path.join(os.path.abspath(events_dir), norm + ".md"))
    if not _in_tree(p, events_dir):
        raise ValueError(f"id 越出 memory 树（解析为 {p}）")
    return p




def _entity_key_late(title):
    from . import hma_core
    return hma_core._entity_key(title)


def _search_blob_late(pkg):
    from . import hma_core
    return hma_core._search_blob(pkg)


def _derive_anchors_late(md_text, max_level=6):
    from . import hma_core
    return hma_core.derive_anchors(md_text, max_level)


def _memory_cls_late():
    from . import hma_core
    return hma_core.Memory


class WriteMixin:
    """写入线方法集合，由 hma_core.Memory 继承（S5 拆分）。"""


    def write(self, id, title="", summary="", aliases=None, tags=None,
              linked=None, body="", created=None, updated=None,
              pkage_created=None, pkage_updated=None,
              anchors=None, embedding=None, trigger=None,
              person=None, location=None, topic=None, event_date=None,
              features=None, record_change=True, integrity_check=False,
              force_empty_body=False):
        """写/改一个事件包：原子写 .md + upsert 索引。
        anchors: 可选子事件锚点列表 [{Chapter, about, keywords}]（C+A 对象锚点，
        V2 形态，无 tags/locator），挂在同一个 .md 正文上，实现「1 个包 + 多锚点」
        的细粒度召回。
        trigger: 调用方标识（仅作元信息标签，当前不落任何变更日志；
                 历史曾用于 changes/ 快照审计，R59 续3 已废弃）。
        V2 注意：aliases / features 入参会被折叠进四要素 dict（person/location/topic），
        不再有独立存储列；时间用 pkage_created/pkage_updated（兼容旧 created/updated）。
        """
        created = pkage_created or created
        updated = pkage_updated or updated
        updated = updated or str(date.today())
        if anchors is None and body:
            anchors = _derive_anchors_late(body)
        # 遗留 aliases/features 折叠进四要素（V2 无独立列）
        person = _merge_legacy(person, aliases, features)
        pkg = EventPackage(
            id=id, title=title, summary=summary,
            tags=tags or [], linked=linked or [],
            created=created, updated=updated, body=body,
            anchors=anchors,
            person=person, location=location, topic=topic, event_date=event_date,
        )
        # 若已存在且调用方未显式给 created，保留原 created（记录时间不变）；
        # 调用方显式传 created 时以调用方为准（如适配器写入收录时间）。
        existing = self.read(id)
        if existing and created is None:
            pkg.created = existing.created

        path = _safe_md_path(self.events_dir, id)   # P2-D：越界/绝对路径在此被拒
        # 读磁盘现有正文（供门禁做覆盖保护）
        existing_body = ""
        if os.path.exists(path):
            try:
                _old = open(path, encoding="utf-8").read()
                existing_body = _old.split("---", 2)[-1] if _old.count("---") >= 2 else _old
            except OSError:
                existing_body = ""
        # —— 编排者职责：显式洗白 / 降级解锁 + 唯一门禁校验 ——
        # 1. 正常模式：body 和 anchors 都有，解除残缺锁。
        #    注意：不走 mark_as_complete（那是"AI 显式补全且 keywords 必填"语义），
        #    因为 Memory.write 是受控编排者，anchors 常来自 derive_anchors（keywords 空），
        #    属合法来源。门禁 assert_writable 仍查 anchors 非空（不查 keywords，
        #    因 derive 派生的空 keywords 是系统常态，非异常）。
        if (body or "").strip() and anchors:
            pkg._is_partial = False
        # 2. force 模式降级解锁：允许 body 为空，但不允许 fm_only 来源，且必须有 anchors。
        #    此时包不是"完整包"，而是"被显式授权的降级包"，直接解开状态锁供
        #    to_markdown 放行（不走 mark_as_complete 的"补全"语义，因语义互斥）。
        elif force_empty_body and anchors and not (body or "").strip():
            if not getattr(pkg, '_fm_only_read', False):
                pkg._is_partial = False  # 显式降级解锁，不调 mark_as_complete
            # 若是 fm_only 包，_is_partial 保持 True，稍后由 assert_writable 拦截
        # 3. 唯一门禁校验（原 R-safety 独立块已并入此处，消除双校验漂移）
        pkg.assert_writable(
            existing_body=existing_body,
            allow_empty_body=force_empty_body,
        )
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(pkg.to_markdown())
        os.replace(tmp, path)  # 原子落盘，崩溃安全

        self._upsert(pkg, path, embedding)
        # 写入侧反推（可选项，不阻断落库）：检测刚落库的实体是否缺独有弧段，
        # 返回 warning 清单供 Agent 侧反推用户补独有关键词。默认关闭以保持
        # write() 返回 path 的旧契约不变。
        if integrity_check:
            ek = _entity_key_late(title)
            warnings = self.check_write_integrity(target_ekeys={ek}, soft_k=3)
            return {"path": path, "warnings": warnings}
        return path

    def _upsert(self, pkg, path, embedding=None, package_id=None):
        pid = package_id if package_id is not None else self.package_id
        c = self._conn()
        c.execute("""
            INSERT INTO events
                (package_id,title,summary,tags,linked,filepath,
                 pkage_created,pkage_updated,embedding,anchors,
                 person,event_date,location,topic,search_blob)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(package_id, filepath) DO UPDATE SET
                title=excluded.title, summary=excluded.summary,
                tags=excluded.tags, linked=excluded.linked,
                filepath=excluded.filepath,
                pkage_updated=excluded.pkage_updated, embedding=excluded.embedding,
                anchors=excluded.anchors,
                person=excluded.person, event_date=excluded.event_date,
                location=excluded.location, topic=excluded.topic,
                search_blob=excluded.search_blob
        """, (
            pid, pkg.title, pkg.summary,
            json.dumps(pkg.tags, ensure_ascii=False),
            json.dumps(pkg.linked, ensure_ascii=False),
            path, pkg.created, pkg.updated,
            embedding,
            json.dumps(pkg.anchors, ensure_ascii=False),
            json.dumps(pkg.person, ensure_ascii=False),
            pkg.event_date,
            json.dumps(pkg.location, ensure_ascii=False),
            json.dumps(pkg.topic, ensure_ascii=False),
            _search_blob_late(pkg),
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
        m = self if same else _memory_cls_late()(dst_dir)
        try:
            # 保留读取到的全部字段原样写回（含锚点/四要素），不重派生、不丢字段。
            # 仅当锚点为空/缺失时才令 write() 从 body 重新派生。
            # 避免 link() 把对话记录刻意设的单一整体锚点 ["对话记录"] 覆盖成多段派生锚点
            # （query_anchors 会双计同包），以及把 person/event_date/location/topic 清空。
            m.write(pkg.id, pkg.title, pkg.summary, tags=pkg.tags,
                    linked=pkg.linked, body=pkg.body, created=pkg.created,
                    updated=pkg.updated,
                    anchors=pkg.anchors if pkg.anchors else None,
                    person=pkg.person, location=pkg.location,
                    topic=pkg.topic, event_date=pkg.event_date)
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

    def check_write_integrity(self, target_ekeys=None, soft_k=3):
        """写入侧反推入口：检测缺乏独有弧段的实体（落库前/后均可调用，不阻断写入）。

        target_ekeys=None → 扫描全部实体（lint 模式，可批量体检记忆库）；
        传具体 ekey 集合（如刚落库包 title 的 _entity_key）→ 只查那一个。
        始终基于『全局』实体特征索引判定唯一性。返回 warning 列表（见 _missing_unique_arcs）。
        """
        idx = self._entity_feature_index()  # 全局
        global_count = {}
        for ent in idx.values():
            for f in ent["features"]:
                global_count[f] = global_count.get(f, 0) + 1
        return self._missing_unique_arcs(idx, global_count, target_ekeys, soft_k)

    # ---- IDF 权重（完全可由 index.db 重建，不引入新持久状态）-------------
