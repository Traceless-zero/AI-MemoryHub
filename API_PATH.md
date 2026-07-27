# HMA 付费 / 本地 LLM API 路径（草稿，待补）

> 这是「大概」——接口骨架已就绪，细节留给接手的人对着改。
> 设计铁律见文末，无论怎么补都不许动。

## 现状（已落地）

- `hma/llm_adapter.py`：通用大模型适配器，**零第三方依赖**（仅标准库 `urllib`）。
  - `OpenAICompatibleAdapter`：OpenAI / Groq / Together / DeepSeek / Moonshot / Ollama(openai 兼容) / vLLM / LM Studio……
  - `AnthropicAdapter`：Claude 官方 API
  - `get_adapter(provider="openai", **kwargs)` 工厂，读 `HMA_LLM` 环境变量
- `hma/engine/handlers/note.py`：`mode=note` 入口，env 闸门：
  - `adapter = get_adapter() if os.environ.get("HMA_LLM") else None`
  - 无 key → `run_ingest` 退化为单包启发式（永远可用）
  - 有 key → 走 `llm_adapter` 真实 LLM
- `hma/server.py`：MCP 工具 `memory_ingest`（第 5 个工具），`_h_ingest` 按 env 决定加载适配器
- `examples/basic_agent.py`：最小 agent 循环样例（已演示 `get_adapter()` 接 key）

## 配置（env）

```bash
export HMA_LLM=openai        # 或 anthropic
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://...   # 可选，自托管 / 中转
export OPENAI_MODEL=gpt-4o
# 或 anthropic：
export ANTHROPIC_API_KEY=...
export ANTHROPIC_MODEL=claude-...
```

## 待补（TODO，留待接手）

- [ ] 配真实 key 后跑一遍 end-to-end，记录延迟 / 失败模式
- [ ] `llm_adapter` 的流式 / 重试 / 超时策略
- [ ] MCP `memory_ingest` 在真实客户端里的接线（本仓库只做引擎，客户端由 skill 接入）
- [ ] 多轮 tool-call 循环的工具结果回填（已有 `assistant_with_tools` / `tool_result` 归一化，待压测）
- [ ] 失败降级路径的回归测试（key 无效 / 断网 → 自动回启发式）
- [ ] 计费 / 限额护栏
- [ ] 中文 / 长上下文场景下的 prompt 调优（当前 `ingest_prompt` 偏向短文本样例）
- [ ] 与 `hma-ingest` 技能（零成本 Agent 路径）的文档对照，确保两条路产出同构

## 设计铁律（不动）

- 引擎落库层（`Memory.write` / `index.db`）与「谁做理解」解耦：理解交给 LLM 适配器，确定性写交脚本。
- 两条路（零成本 Agent 路径 `hma-ingest` 技能 / 付费 `note`+`llm_adapter`）产出**同构**的包结构，互不冲突。
- 无论哪条路，`.md` 为唯一权威源，`index.db` 可全量重建。
- 无状态检索铁律：确定性查询，拒绝热度 / 新鲜度等权重。
