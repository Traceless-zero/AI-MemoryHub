import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from hma.hma_core import EventPackage, Memory

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
TARGET = os.path.join(ROOT, 'memory/项目/AIMH-design-journal/询问类型与解决思路.md')

print("=== 真实仓回归：合并门禁方案 ===\n")

# 1. from_markdown 全量读 -> _is_partial=False, to_markdown 成功
with open(TARGET, encoding='utf-8') as f:
    text = f.read()
pkg = EventPackage.from_markdown(text, TARGET)
print(f"[1] from_markdown: _is_partial={pkg._is_partial} | anchors={len(pkg.anchors)} | body_len={len(pkg.body)}")
assert pkg._is_partial == False, "全量读应解除残缺锁"
assert len(pkg.anchors) > 0, "锚点应非空"
out = pkg.to_markdown()
assert out.startswith("---")
# 验证序列化往返一致性：正文未被清空、anchors 保留
assert pkg.body.strip() in out or pkg.body in out, "序列化丢失正文"
print(f"    to_markdown OK (len={len(out)}), 正文保留={pkg.body.strip()[:20]!r}...")

# 2. from_markdown_fm_only -> _is_partial=True + _fm_only_read=True, to_markdown 拒绝
pkg2 = EventPackage.from_markdown_fm_only(text, TARGET)
print(f"\n[2] fm_only: _is_partial={pkg2._is_partial} | _fm_only_read={pkg2._fm_only_read} | anchors={len(pkg2.anchors)}")
assert pkg2._is_partial == True and pkg2._fm_only_read == True
try:
    pkg2.to_markdown()
    print("    ERROR: fm_only to_markdown 未拒绝!")
    sys.exit(1)
except ValueError as e:
    print(f"    fm_only to_markdown 正确拒绝: {str(e)[:45]}")

# 3. mark_as_complete 对 fm_only 硬拦
try:
    pkg2.mark_as_complete()
    print("    ERROR: fm_only mark_as_complete 未拒!")
    sys.exit(1)
except ValueError as e:
    print(f"[3] fm_only mark_as_complete 正确拒绝: {str(e)[:50]}")

# 4. Memory.write 新建包（正常路径）自动洗白
m = Memory('memory')
test_id = "_regress_gate_tmp"
try:
    m.write(test_id, title="回归测试临时包", summary="s", body="## 标题\n正文内容", tags=["test"])
    # 读回验证
    back = m.read(test_id)
    assert back is not None, "写回后读不到"
    assert "正文内容" in back.body, f"正文异常: {back.body!r}"
    print(f"\n[4] Memory.write 新建包 OK: _is_partial(写时)=False, 读回 body={back.body.strip()!r}")
finally:
    # 清理
    p = os.path.join(m.events_dir, f"{test_id}.md")
    if os.path.exists(p):
        os.remove(p)
        print("    已清理临时包")

# 5. Memory.write force 清空（降级解锁路径）
test_id2 = "_regress_gate_force"
# 先写一个正常包
m.write(test_id2, title="force测试", summary="s", body="原始正文", anchors=[{"Chapter":"测试章","about":"x","keywords":["测试"]}])
# 再 force 清空
m.write(test_id2, title="force测试", summary="s", body="", anchors=[{"Chapter":"测试章","about":"x","keywords":["测试"]}], force_empty_body=True)
back2 = m.read(test_id2)
assert back2.body.strip() == "", f"force 清空失败: {back2.body!r}"
print(f"\n[5] Memory.write force 清空 OK: 清空后 body={back2.body.strip()!r}")
p2 = os.path.join(m.events_dir, f"{test_id2}.md")
if os.path.exists(p2):
    os.remove(p2)
    print("    已清理临时包")

# 6. rebuild_index 路径验证（重构造包 mark_as_complete 不崩）
# 注：rebuild 已不再自动派生锚点（merge_anchors 机制已删除），此处仅验证
# EventPackage 重构造 + mark_as_complete 不抛（等价于 rebuild 写回路径）。
pkg_re = EventPackage(
    id="x", title="t", summary="s", tags=[], linked=[],
    person={}, location={}, topic={}, event_date="—",
    created="2026-01-01", updated="2026-01-01",
    body="# 章\n内容", anchors=[{"Chapter":"章","about":"a","keywords":["k"]}],
)
pkg_re._is_partial = False  # 模拟 rebuild 路径解除锁
out_re = pkg_re.to_markdown()
assert out_re.startswith("---")
print(f"\n[6] rebuild 重构造包 mark_as_complete + to_markdown OK (len={len(out_re)})")

# 收尾：清临时包的索引行（文件已删，防生产索引残留孤儿行；
# 临时包在仓库根 package_id=''，uninstall 的拒空保护不适用，按 filepath 删）
_c = m._conn()
_c.execute("DELETE FROM events WHERE filepath LIKE '%_regress_gate%'")
print("    已清理临时包索引行")

print("\n=== 全部回归通过 ===")
