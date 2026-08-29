# -*- coding: utf-8 -*-
"""拉出 HMA 前台索引(memory/index.db)的 schema + 第一行真实数据，给用户看实际存了啥。"""
import sqlite3, os, json

P = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "memory", "index.db")
if not os.path.exists(P):
    print("NO index.db at", P)
else:
    con = sqlite3.connect(P)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(events)")
    cols = [r[1] for r in cur.fetchall()]
    print("COLUMNS:", cols)
    cur.execute("SELECT COUNT(*) FROM events")
    print("ROW COUNT:", cur.fetchone()[0])
    cur.execute("SELECT * FROM events LIMIT 1")
    row = cur.fetchone()
    if row:
        print("\n--- 第一行真实数据 ---")
        for c, v in zip(cols, row):
            if c in ("aliases", "tags") and v:
                try:
                    v = json.loads(v)
                except Exception:
                    pass
            print(f"  {c}: {v!r}")
    else:
        print("events 表为空")
    con.close()
