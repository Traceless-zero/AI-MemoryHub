# -*- coding: utf-8 -*-
"""类型 8 计数（db_aggregate）【沙箱】回归测试。

针对 memory_sandbox/memory/index.db（数据副本）做只读校验，证明新写的
db_aggregate 在「沙箱数据」上 7 护栏全绿、口径正确，再决定回归生产。

注意：沙箱 index.db 的 filepath 列是复制时残留的真实仓绝对路径，故 scope
收束在沙箱下恒为 0（预期）；scope 收束已在 regress_aggregate.py（真实仓）验证。

用法（仓库根下）：
  python scripts/tests/regress_aggregate_sandbox.py
退出码 0=全过，非 0=有 FAIL。
"""
import os
import sqlite3
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from hma.hma_core import db_aggregate

SB = os.path.join(REPO, "memory_sandbox", "memory", "index.db")
if not os.path.exists(SB):
    print("SKIP: 找不到沙箱", SB, "（先跑 rm -rf memory_sandbox && mkdir -p memory_sandbox && cp -r memory/. memory_sandbox/memory/）")
    sys.exit(0)

fails = []


def ok(name, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {extra}")
    if not cond:
        fails.append(name)


# ---- 护栏 5：只读连接拒绝写 ----
try:
    cx = sqlite3.connect(f"file:{SB}?mode=ro", uri=True)
    cx.execute("UPDATE events SET title='x' WHERE 1=0")
    ok("护栏5 只读连接拒绝写", False, "mode=ro 仍允许了写")
    cx.close()
except sqlite3.OperationalError:
    ok("护栏5 只读连接拒绝写", True, "(sqlite3.OperationalError 已拦截)")

# ---- 各 unit 计数（沙箱全仓） ----
n_pkg = db_aggregate(SB, "packages")
n_evt = db_aggregate(SB, "events")
n_per = db_aggregate(SB, "persons")
n_loc = db_aggregate(SB, "locations")
n_top = db_aggregate(SB, "topics")
print(f"  -> 沙箱全仓: packages={n_pkg} events={n_evt} persons={n_per} locations={n_loc} topics={n_top}")
ok("packages 计数 >0", n_pkg > 0)
ok("events 计数 >0", n_evt > 0)
ok("persons 计数 >0", n_per > 0)
ok("locations 计数 >0", n_loc > 0)
ok("topics 计数 >0", n_top > 0)

# 交叉验证实体计数（独立手写 SQL 口径，沙箱）
cx = sqlite3.connect(f"file:{SB}?mode=ro", uri=True)
ref_per = cx.execute(
    "SELECT COUNT(DISTINCT key) FROM events, json_each(events.person) "
    "WHERE events.person IS NOT NULL AND events.person<>'' AND json_valid(events.person)=1"
).fetchone()[0]
ref_loc = cx.execute(
    "SELECT COUNT(DISTINCT key) FROM events, json_each(events.location) "
    "WHERE events.location IS NOT NULL AND events.location<>'' AND json_valid(events.location)=1"
).fetchone()[0]
ref_top = cx.execute(
    "SELECT COUNT(DISTINCT key) FROM events, json_each(events.topic) "
    "WHERE events.topic IS NOT NULL AND events.topic<>'' AND json_valid(events.topic)=1"
).fetchone()[0]
cx.close()
ok("persons 与独立 SQL 一致", n_per == ref_per, f"{n_per} vs {ref_per}")
ok("locations 与独立 SQL 一致", n_loc == ref_loc, f"{n_loc} vs {ref_loc}")
ok("topics 与独立 SQL 一致", n_top == ref_top, f"{n_top} vs {ref_top}")

# ---- 护栏 2+3：filters 列白名单 + 值参数化 ----
mar_pkgs = db_aggregate(SB, "packages", filters={"event_date": ("like", "2026-03%")})
cx = sqlite3.connect(f"file:{SB}?mode=ro", uri=True)
ref_mar = cx.execute(
    "SELECT COUNT(DISTINCT package_id) FROM events WHERE event_date LIKE ?",
    ("2026-03%",)).fetchone()[0]
cx.close()
ok("filters event_date like 确定且一致", mar_pkgs == ref_mar and mar_pkgs >= 0, f"{mar_pkgs} vs {ref_mar}")

try:
    db_aggregate(SB, "packages", filters={"password": ("=", "x")})
    ok("护栏2 非法列拒绝", False)
except ValueError:
    ok("护栏2 非法列拒绝", True)
try:
    db_aggregate(SB, "packages", filters={"event_date": (">", "2020")})
    ok("护栏2 非法算子拒绝", False)
except ValueError:
    ok("护栏2 非法算子拒绝", True)

# ---- 护栏 7：scope（沙箱 filepath 残留真实仓路径，恒为 0 属预期） ----
scoped0 = db_aggregate(SB, "packages", scope="原创角色")
ok("scope 收束在沙箱下恒为0(预期:filepath残留)", scoped0 == 0,
   f"scope=原创角色 -> {scoped0}（沙箱 filepath 指向真实仓，LIKE 不中；非缺陷）")

# ---- 护栏 6：return_list + 500 上限 ----
lst = db_aggregate(SB, "persons", return_list=True)
ok("return_list persons 形态正确", isinstance(lst, list) and len(lst) == n_per)
big = db_aggregate(SB, "persons", return_list=True, top_k=99999)
ok("护栏6 top_k 硬上限 500", len(big) <= 500, f"len={len(big)}")
evt_lst = db_aggregate(SB, "events", return_list=True)
ok("events return_list 形态 pkg::Chapter", all("::" in x for x in evt_lst) and len(evt_lst) == n_evt)

print("\n[scope 收束真实有效性] 见真实仓回归 regress_aggregate.py：全仓 11 包 -> scope=原创角色 1 包 / 38 子事件")
print("\n=== 沙箱结果 ===", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
