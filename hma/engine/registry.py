# -*- coding: utf-8 -*-
"""HMA 引擎的「分支接口」—— 模式到处理器的注册表。

=====================================================================
这是用户明确要求的「留个分支接口」：引擎主体保持通用、固定不变，
每种新的落库方式（mode）只需注册一个 handler，无需改动派发逻辑。

  · 内置 mode（见 handlers/）：
      packs       —— 显式清单：源文件里写死每个事件包，逐个落库（最通用）
      oc_dossier  —— 结构化 dossier → 按三层铁律确定性切成基础/故事/拓展包
      note        —— 原始文本 → 走 ingest 管线（LLM 理解或启发式兜底）

  · 扩展新 mode：在 handlers/ 下新建模块，用 @register("your_mode") 装饰
    处理函数即可自动接入。HMA 不是 OC 专用——它是通用事件记忆引擎，
    OC 装卸只是 packs / oc_dossier 两个 handler 的一种应用。

handler 签名：
    def handler(doc, *, root_override=None, base_dir=None,
                trigger="engine.derive") -> list[str]
返回落库的事件包 id 列表。
=====================================================================
"""

HANDLERS = {}


def register(mode):
    """装饰器：把一个处理函数注册为某 mode 的 handler。"""
    def deco(fn):
        if mode in HANDLERS:
            raise ValueError(f"mode 已注册: {mode}")
        HANDLERS[mode] = fn
        return fn
    return deco


def available_modes():
    return sorted(HANDLERS.keys())


def dispatch(mode, doc, **kw):
    """按 mode 派发到对应 handler。"""
    if mode not in HANDLERS:
        raise KeyError(
            f"未知 mode: {mode!r}；已注册: {available_modes()}"
        )
    return HANDLERS[mode](doc, **kw)
