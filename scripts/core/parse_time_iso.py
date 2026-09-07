# -*- coding: utf-8 -*-
"""parse_time_iso —— 中文相对时间 → ISO 的 CLI 薄壳。

词表与解析实现在 `hma/time_iso.py`（引擎成员，parse_time_hint 预解析同源）；
本文件只做命令行包装。库用法见 timewords 模块 docstring。
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from hma import time_iso  # noqa: E402

parse = time_iso.parse            # 库用法再导出
parse_text = time_iso.parse_text  # 扫描模式再导出


def main(argv=None):
    ap = argparse.ArgumentParser(description="中文相对时间 → ISO 日期/区间（层级确定性解析，零 ML）")
    ap.add_argument("exprs", nargs="*", help="时间表达式（如 前天 / 上周三 / 上个月15号 / 月底）")
    ap.add_argument("--today", default=None, help="锚点日期 YYYY-MM-DD（默认真实今天）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（机器消费）")
    ap.add_argument("--scan", dest="scan_text", default=None, help="从自由文本中抽取时间表达式")
    args = ap.parse_args(argv)

    today = None
    if args.today:
        y, m, d = (int(x) for x in args.today.split("-"))
        today = __import__("datetime").date(y, m, d)

    results = []
    if args.scan_text is not None:
        results = [{"expr": r["expr"], **r} for r in time_iso.parse_text(args.scan_text, today)]
    else:
        for e in args.exprs:
            r = time_iso.parse(e, today)
            if r:
                results.append({"expr": e, **r})
            else:
                results.append({"expr": e, "kind": "unrecognized"})

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            if r["kind"] == "unrecognized":
                print("%s → 无法识别" % r["expr"])
            elif r["kind"] in ("before", "after"):
                print("%s → %s %s（边界 %s）" % (r["expr"], r["kind"], r["boundary"]))
            elif r["kind"] == "day":
                print("%s → %s（单日）" % (r["expr"], r["start"]))
            else:
                print("%s → %s .. %s（区间）" % (r["expr"], r["start"], r["end"]))
    return 0 if all(r.get("kind") not in (None, "unrecognized") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
