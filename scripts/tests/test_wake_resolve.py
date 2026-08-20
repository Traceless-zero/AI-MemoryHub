# -*- coding: utf-8 -*-
"""
OC “叫名字唤醒扮演”解析层测试 harness
======================================
把「叫名字 / 叫代号 → 解析到 base 包」的用例固化成可重复运行的脚本。

用法：
    cd E:/BaiduNetdiskDownload/项目/AIMH
    python scripts/tests/test_wake_resolve.py

每条用例：(用户原话, 期望解析到的 OC name；None 表示不应命中)
断言：oc_registry.find 解析出的 oc["name"] 与期望一致（含“不应命中”的负向用例）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
CORE = os.path.join(PROJECT, "core")   # oc_registry 已收拢至 scripts/core/
sys.path.insert(0, HERE)        # 让 import oc_registry 能跑通其内部 import
sys.path.insert(0, PROJECT)     # 让 hma.hma_core 可 import
sys.path.insert(0, CORE)        # 收拢后 oc_registry 位于 scripts/core/

import oc_registry as R  # noqa: E402

# (用户原话, 期望 OC name；None=不应命中)
# 注：oc_registry 演进后 oc["name"] 为中文全名（如 维罗妮卡·夏·雪莱），非旧 id。
TESTS = [
    ("维罗妮卡你在干嘛",        "维罗妮卡·夏·雪莱"),   # 部分名（首段）
    ("午夜魅影你出来",          "维罗妮卡·夏·雪莱"),   # 代号（从基础包正文抽取）
    ("维罗妮卡·夏·雪莱你在干嘛", "维罗妮卡·夏·雪莱"),   # 全名
    ("你知道维罗妮卡吗",        "维罗妮卡·夏·雪莱"),   # 名字在句中
    ("托尼·斯塔克你在干嘛",     None),        # 负向：不是已登记 OC
    ("你好",                    None),        # 负向：无名字
]


def main():
    # discover 默认扫 ./memory 下的 原创角色/（实时解析，无需快照）
    ocs = R.discover("memory")
    passed = 0
    failed = 0
    print(f"OC 唤醒解析测试 ({len(TESTS)} 用例)\n")
    for text, exp in TESTS:
        oc, key = R.find(text, ocs)
        got = oc["name"] if oc else None
        ok = (got == exp)
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        if oc:
            detail = f"key='{key}' -> {got}"
        else:
            detail = "未命中"
        print(f"[{status}] 『{text}』 期望={exp}  实际=({detail})")
    print(f"\n结果：{passed} 通过 / {failed} 失败 / 共 {len(TESTS)}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
