# -*- coding: utf-8 -*-
"""Type 8 计数（db_aggregate / memory_aggregate）回归测试。

对真实仓 index.db 做只读校验（db_aggregate 强制 mode=ro，绝不写库）：
  - 5 个 unit 的计数口径与独立手写 SQL 一致
  - 7 道护栏：只读连接拒写 / 列白名单 / 算子白名单 / 值参数化 / 实体列 json_each
    / 行数上限 500 / 显式 scope 收束
  - Memory.aggregate 方法转发签名正确

用法（仓库根下）：
  python scripts/tests/regress_aggregate.py
退出码 0=全过，非 0=有 FAIL。
"""
import os
import sqlite3
import sys

# 让脚本在仓库根直接跑：把 repo 根加入 sys.path（hma 包在仓库根）
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from hma import hma_core
from hma.hma_core import db_aggregate, Memory

DB = os.path.join(REPO, "memory", "index.db")
if not os.path.exists(DB):
    print("SKIP: 找不到", DB)
    sys.exit(0)

fails = []


def ok(name, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {extra}")
    if not cond:
        fails.append(name)


# ---- 护栏 5：只读连接拒绝写 ----
try:
    cx = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cx.execute("UPDATE events SET title='x' WHERE 1=0")
    ok("护栏5 只读连接拒绝写", False, "mode=ro 仍允许了写")
    cx.close()
except sqlite3.OperationalError:
    ok("护栏5 只读连接拒绝写", True, "(sqlite3.OperationalError 已拦截)")

# ---- 各 unit 计数（全仓） ----
n_pkg = db_aggregate(DB, "packages")
n_evt = db_aggregate(DB, "events")
n_per = db_aggregate(DB, "persons")
n_loc = db_aggregate(DB, "locations")
n_top = db_aggregate(DB, "topics")
print(f"  -> 全仓: packages={n_pkg} events={n_evt} persons={n_per} locations={n_loc} topics={n_top}")
ok("packages 计数 >0", n_pkg > 0)
ok("events 计数 >0", n_evt > 0)
ok("persons 计数 >0", n_per > 0)
ok("locations 计数 >0", n_loc > 0)
ok("topics 计数 >0", n_top > 0)

# 交叉验证实体计数（独立手写 SQL 口径）
cx = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
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
mar_pkgs = db_aggregate(DB, "packages", filters={"event_date": ("like", "2026-03%")})
cx = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
ref_mar = cx.execute(
    "SELECT COUNT(DISTINCT package_id) FROM events WHERE event_date LIKE ?",
    ("2026-03%",)).fetchone()[0]
cx.close()
ok("filters event_date like 确定且一致", mar_pkgs == ref_mar and mar_pkgs >= 0, f"{mar_pkgs} vs {ref_mar}")

try:
    db_aggregate(DB, "packages", filters={"password": ("=", "x")})
    ok("护栏2 非法列拒绝", False)
except ValueError:
    ok("护栏2 非法列拒绝", True)
try:
    db_aggregate(DB, "packages", filters={"event_date": (">", "2020")})
    ok("护栏2 非法算子拒绝", False)
except ValueError:
    ok("护栏2 非法算子拒绝", True)

# ---- 护栏 7：scope 收束（正向，非空子树） ----
all_p = db_aggregate(DB, "packages")
scoped_p = db_aggregate(DB, "packages", scope="原创角色")
ok("scope 收束到非空子集", 0 < scoped_p < all_p, f"全仓={all_p} scope=原创角色={scoped_p}")

# ---- 护栏 6：return_list + 500 上限 ----
lst = db_aggregate(DB, "persons", return_list=True)
ok("return_list persons 形态正确", isinstance(lst, list) and len(lst) == n_per)
big = db_aggregate(DB, "persons", return_list=True, top_k=99999)
ok("护栏6 top_k 硬上限 500", len(big) <= 500, f"len={len(big)}")
evt_lst = db_aggregate(DB, "events", return_list=True)
ok("events return_list 形态 pkg::Chapter", all("::" in x for x in evt_lst) and len(evt_lst) == n_evt)

# ---- Memory.aggregate 方法转发 ----
m = Memory("memory")
try:
    rp = m.aggregate("packages")
    ok("Memory.aggregate 转发正确", isinstance(rp, int) and rp == n_pkg, f"{rp} vs {n_pkg}")
finally:
    m.close()

print("\n=== 结果 ===", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
