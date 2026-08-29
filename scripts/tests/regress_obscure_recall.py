"""生产级回归：验证 memory_obscure_recall 工具端到端（走真实引擎，非沙箱内联）。

断言：
  R1 显式锁章（scope_mode=explicit, scope_chapter=赎回）→ 候选段数骤降（< 全包）
  R2 每段 C/A 从真实锚点抽到（about 非空）
  R3 路线一无果 → 自动拒答 + 强制降级转路线二（route=="two", auto_abstain==True）
  R4 全局模式（scope_mode=global）能捞到候选（不静默漏）
"""
import sys, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from hma.hma_core import Memory

ROOT_MEM = os.path.join(ROOT, "memory")
PKG = "原创角色/示例角色/demo-origin"
OBJ = "唱片"
Q = "示例角色在伊斯坦布尔那张唱片封面什么样"

m = Memory(ROOT_MEM)

# R1 + R3：显式锁章「赎回」
r_explicit = m.obscure_recall(q=Q, obj_token=OBJ, package_id=PKG,
                              scope_chapter="赎回", scope_mode="explicit", top_k=5)
print("=== R1/R3 显式锁章「赎回」 ===")
print(f"route={r_explicit['route']}  auto_abstain={r_explicit['auto_abstain']}")
print(f"候选段数={len(r_explicit['cards'])}  scope={r_explicit['scope']['label']}")
print(f"message={r_explicit['message']}")
for c in r_explicit["cards"]:
    print(f"  [C]{c['chapter']}\n  [A]{c['about'][:60]}...\n  [段]{c['segment'][:50]}...")

# R2：C/A 非空
r2 = all(c["about"] for c in r_explicit["cards"])
print(f"\nR2 每段 about 非空：{'PASS' if r2 else 'FAIL'}")

# R4：全局模式
r_global = m.obscure_recall(q=Q, obj_token=OBJ, package_id=PKG,
                            scope_mode="global", top_k=20)
print(f"\n=== R4 全局模式 ===")
print(f"route={r_global['route']}  候选段数={len(r_global['cards'])}")
r4 = len(r_global["cards"]) > 0

# 判定
r1 = len(r_explicit["cards"]) < len(r_global["cards"])
r3 = (r_explicit["route"] == "two") and r_explicit["auto_abstain"]
print(f"\nR1 锁章缩圈（{len(r_explicit['cards'])}<{len(r_global['cards'])}）：{'PASS' if r1 else 'FAIL'}")
print(f"R3 路线一无果降级转路线二：{'PASS' if r3 else 'FAIL'}")
print(f"R4 全局不静默漏：{'PASS' if r4 else 'FAIL'}")
allpass = r1 and r2 and r3 and r4
print(f"\n总判定：{'✅ 全部 PASS' if allpass else '❌ 有 FAIL'}")
sys.exit(0 if allpass else 1)
