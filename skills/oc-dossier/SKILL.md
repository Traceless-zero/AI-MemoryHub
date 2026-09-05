---
name: oc-dossier
description: |
  OC / 角色档案 / 人物档案的全生命周期技能（对应 HMA「原创角色」命名空间）。覆盖两个互补入口：
  （A）存角色——用户丢来文字 / 文件说"把这个角色存下来""从书里摘个人物"时，先跑 oc_classify.py 拿确定性 verdict，再分流：structured→dossier_build.py 自动切片落库；ambiguous→AI 按三层铁律理解抽取落库；两路落库后都刷 oc_registry 快照。
  （B）唤醒角色——对话里叫到已落库 OC 的名字 / 代号并像对其说话时，用 oc_registry.py find 确定性解析到基础包，进入角色扮演，按需惰性召回故事 / 拓展包。
  三层铁律：① 基础包必有且仅 1 个（姓名 + 形象 + 语气，扮演最小单元）；② origin 包（背景故事包，默认必有，哪怕一行字也独立成包，仅无背景故事者省略）；③ 拓展包有则分。
  命中即加载：关键词 OC、角色档案、人物档案、dossier、存角色、摘角色、收进记忆、角色扮演、唤醒、扮演、叫名字、按名启动、identity anchor。
---

# OC Dossier（存 + 唤醒 · 骨架）

> **权威全文**：`memory/项目/AIMH-design-journal/拆包与收录规范.md` §4（T29 钉映射）；方法/模板/范例 `references/method.md`、`references/flow.md`。
> **执行规则**：按召回键调 `mcp__aimh__memory_query_anchors`；**ABSTAIN → 停止并报告，勿即兴**。

## 存角色（store）

1. **首行铁律**：不自判结构化——先跑 `oc_classify.py classify <源文件>` 拿确定性 verdict 分流。
2. **路 A structured**：`dossier_build.py --id <角色id> --source <源文件>` 确定性切片。召回键 `["oc_classify"]`
3. **路 B ambiguous**：AI 按三层铁律抽取（base/origin/ext），直写 `Memory.write`（SCHEMA 契约；**背景故事原样收录禁止综述化**；不动用户源文件）。召回键 `["存角色流程"]`
4. **三层铁律**：基础包必有仅 1 个（姓名+形象+语气）；origin 默认必有（一句短语也独立成包）；拓展有则分。
5. **后置**：`oc_registry.py find "名字"` 验证可解析（实时扫描，无 index 子命令）。

## 唤醒角色（wake）

1. `oc_registry.py find "<用户原话>"` 名字解析（未命中 → 不进入扮演，正常助手响应）。
2. `Memory(root).read_body(base_id)` 启动基础包（姓名+形象+语气 = 扮演最小单元）。
3. 以该 OC 语气回应本句；**惰性召回**：问起源 → origin `query_anchors`/`read_section`；问能力/关系 → ext `read_section`；不相关问题不塞背景。
4. **身份边界**：扮演即该 OC（不暴露 AI）；退出信号（真名/"退出角色"/"你是 AI 吗"）立即交还；唤醒只读不写。

## 护栏

- 范例与测试一律虚构角色，真实用户 OC 内容不进技能/脚本。
- 隐私与内容主权：工程红线 §4（机密不进 memory；私有包 C 类不碰）。
- 修正需求回流存角色流程；唤醒只读。
