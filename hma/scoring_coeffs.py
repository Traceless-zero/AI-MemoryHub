# -*- coding: utf-8 -*-
"""
AIMH 打分系数集中配置（scoring_coeffs）—— 派生式框架 v2。

设计原则（用户 2026-08-22 决策）：
  1. 整个系统只有一个魔法数字 BASE_UNIT（代表「一次核心字段精确命中」的基准分）。
  2. 其余所有档位 = BASE_UNIT × 字段重要性(FIELD_IMP) × 匹配确定性(MATCH) 派生，
     不再手写孤立数字，调一个系数全局联动且比例可解释。
  3. 覆盖度饱和：多词命中用 1 - exp(-SAT_K × n) 压住堆词虚高，取代逐词 ×N 累加。
  4. AI 流程优先：理解层吐出干净实体词，不产垃圾二元，故 GARBAGE 档在 AI 流下不触发
     （仍保留常量供机械流兼容，但框架主体只看 EXACT / CONTAINS 两档）。

匹配确定性分级（MATCH）：
  exact    = 1.0  整词 / 别名 / id 精确匹配（确定性最高）
  contains = 0.4  子串 / 包含匹配（天然比精确不确定，故打折）
  garbage  = 0.02 机械拆词垃圾二元（AI 流不触发，仅机械流兼容）

字段重要性（FIELD_IMP）：person/topic 是「谁/什么」核心 → 1.0；title 入口 → 0.8；
  tag 分类信号 → 0.8（2026-08-27 治本：真主题 tag 须压过偶提锚点词 100.05，故从 0.6 提到 0.8，落于 anchor 0.667 与 topic 1.0 之间）；summary/body 正文 → 0.3。
"""

import math

# ---- 唯一魔法数字 ----
BASE_UNIT = 150.0   # 一次核心字段精确命中的基准分（用户 2026-08-22 指定试 150）

# ---- 匹配确定性分级 ----
MATCH_EXACT = 1.0
MATCH_CONTAINS = 0.4
MATCH_GARBAGE = 0.02

# ---- 字段重要性 ----
FIELD_IMP = {
    "person": 1.0,
    "topic": 1.0,
    "title": 0.8,
    "tag": 0.8,   # 2026-08-27 治本：从 0.6 提到 0.8，使真主题 tag exact(120) > 偶提锚点词 exact(100.05)
    "anchor": 0.667,   # 锚点 keyword 独立档（B 方案）：介于 tag 0.6 与 title 0.8 之间，低于 proper-noun 1.0
    "summary": 0.3,
    "body": 0.3,
}

# ---- 覆盖度饱和系数 ----
SAT_K = 0.6   # 命中词数饱和速率；1 - exp(-SAT_K × n)

# ---- 派生档位（不再手填，全部由上方系数算出） ----
def _tier(field, match):
    """字段 × 匹配档 → 分数。"""
    return BASE_UNIT * FIELD_IMP[field] * match

# A. 锚点级 _anchor_score（覆盖度语义：每字段命中取最高档一次，不乘词数）
ANCHOR_TITLE_EXACT = _tier("title", MATCH_EXACT)      # BASE_UNIT*0.8*1.0
ANCHOR_TITLE_SUBSTR = _tier("title", MATCH_CONTAINS)   # BASE_UNIT*0.8*0.4
ANCHOR_SUMMARY_SUBSTR = _tier("summary", MATCH_CONTAINS)  # BASE_UNIT*0.3*0.4
ANCHOR_TAG_EXACT = _tier("tag", MATCH_EXACT)          # BASE_UNIT*0.6*1.0
ANCHOR_TAG_SUBSTR = _tier("tag", MATCH_CONTAINS)      # BASE_UNIT*0.6*0.4
ANCHOR_BODY_EXACT = _tier("body", MATCH_EXACT)        # BASE_UNIT*0.3*1.0
ANCHOR_BODY_SUBSTR = _tier("body", MATCH_CONTAINS)    # BASE_UNIT*0.3*0.4

# B. 包级 _score（覆盖度模型：每词在所有字段取最高档一次）
PKG_ID_EXACT = _tier("title", MATCH_EXACT)            # BASE_UNIT*0.8*1.0（id 视作 title 级）
PKG_ID_SUBSTR = _tier("title", MATCH_CONTAINS)        # BASE_UNIT*0.8*0.4
PKG_PERSON_ALIAS_EXACT = _tier("person", MATCH_EXACT) # BASE_UNIT*1.0*1.0
PKG_PERSON_ALIAS_SUBSTR = _tier("person", MATCH_CONTAINS)  # BASE_UNIT*1.0*0.4
PKG_OTHER_ALIAS_EXACT = _tier("topic", MATCH_EXACT)   # BASE_UNIT*1.0*1.0（描述表达式/别名精确命中）
PKG_OTHER_ALIAS_SUBSTR = _tier("topic", MATCH_CONTAINS)   # BASE_UNIT*1.0*0.4
PKG_TITLE_SUBSTR = _tier("title", MATCH_CONTAINS)     # BASE_UNIT*0.8*0.4
PKG_TAG_EXACT = _tier("tag", MATCH_EXACT)             # BASE_UNIT*0.8*1.0（治本：真主题 tag 压过偶提锚点词 100.05，修复打分文件≠展示文件）
PKG_TAG_SUBSTR = _tier("tag", MATCH_CONTAINS)         # BASE_UNIT*0.8*0.4（随 FIELD_IMP["tag"]=0.8 联动，原 0.6→36 现 48）
PKG_SUMMARY_SUBSTR = _tier("summary", MATCH_CONTAINS) # BASE_UNIT*0.3*0.4
PKG_GARBAGE_BIGRAM = _tier("body", MATCH_GARBAGE)     # BASE_UNIT*0.3*0.02（AI 流不触发）
# 锚点 keyword 独立档（B 方案）：把锚点 keyword 从 proper-noun(topic) 通道移出，改走独立档，
# 不再蹭 proper-noun EXACT=150 —— 治本「哲学」类召回遗漏（锚点 keyword 污染包级聚合）。
PKG_ANCHOR_KW_EXACT = _tier("anchor", MATCH_EXACT)    # BASE_UNIT*0.667*1.0 ≈ 100.05
PKG_ANCHOR_KW_SUBSTR = _tier("anchor", MATCH_CONTAINS)  # BASE_UNIT*0.667*0.4 ≈ 40.02
PKG_TRIVIAL_PENALTY = BASE_UNIT * 0.15                # 比例派生，随 BASE_UNIT 联动

# C. 四要素结构化加权（字段折进 score，有上限轻推）
FIELD_W_PERSON = 4
FIELD_W_TIME = 3
FIELD_W_TOPIC = 2
FIELD_W_LOCATION = 2
FIELD_NUDGE = BASE_UNIT * 0.02    # =BASE_UNIT×0.02（比例派生；BASE=150→3.0）
FIELD_CAP = 0.3                   # 字段贡献封顶比例（不变）
FIELD_ROUTE_BONUS = BASE_UNIT     # =BASE_UNIT（比例派生；BASE=150→150）

# D. BM25 rerank 参数（IR 标准饱和函数，非次数加分，保留不动）
RERANK_K1 = 1.5
RERANK_B = 0.75
RERANK_COV_W = 6.0

# E. 关键词覆盖度布尔奖励（派生：命中≥1 真实词即一次性 +BASE_UNIT×2）
KW_FIXED = BASE_UNIT * 2.0        # =BASE_UNIT×2（覆盖度布尔奖励；BASE=150→300）
KW_BIGRAM_BONUS = BASE_UNIT * 0.1 # 10（垃圾二元，机械流兼容）

# F. 读取侧分差剪切 / 绝对分阈值
#    绝对分阈值：用户 2026-08-22 指定独立参考值 75（不从 BASE 派生，独立可调）
CUTOFF_ABSOLUTE_FLOOR = 75.0
CUTOFF_GAP_FLOOR = CUTOFF_ABSOLUTE_FLOOR   # 平局 d1 退化 floor = 同绝对阈值
CUTOFF_GAP_MULT = 2.0   # 异常大分差判定倍数（放宽防弱实体误杀）

# 命名实体链接 boost（远超普通分，确保唯一赢家）
NAMED_LINK_BOOST = 1_000_000.0

# ---- 覆盖度饱和函数（供 _anchor_score / 包级 _score 调用） ----
def coverage_sat(n_hit):
    """多词命中的饱和因子：命中词数越多，边际贡献递减。n_hit>=1 时返回 (0,1]。"""
    if n_hit <= 0:
        return 0.0
    return 1.0 - math.exp(-SAT_K * n_hit)
