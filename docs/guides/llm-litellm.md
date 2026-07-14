# LLM connection via liteLLM

Nexus routes most LLM providers through **liteLLM**. You host models however you like (vLLM, SGLang, Ollama, LiteLLM proxy, cloud APIs) — Nexus only needs `provider`, `model`, `base_url`, and `api_key` on each agent's `llm` block.

## Per-agent LLM selection

Each `AgentConfig` has its own `llm`. Text and voice agents in the same manifest can use different models, tools, and `default_params`.

```yaml
defaults:
  llm_fast: &llm_fast
    provider: litellm
    model: ${ENV:VOICE_LLM_MODEL|ollama/qwen3:4b}
    base_url: ${ENV:LITELLM_BASE_URL|http://localhost:4000}
    api_key: ${ENV:LITELLM_API_KEY|}
    default_params:
      max_tokens: 150
      temperature: 0.7

  llm_smart: &llm_smart
    provider: litellm
    model: ${ENV:TEXT_LLM_MODEL|openai/gpt-4o-mini}
    base_url: ${ENV:LITELLM_BASE_URL|http://localhost:4000}
    default_params:
      max_tokens: 4096

agents:
  erp_assistant:
    llm: *llm_smart
    tool_plugins: [erp_tools]

  voice_assistant:
    modality: voice_cascaded
    agent:
      llm: *llm_fast
      tool_plugins: [erp_tools]   # same or different tools
```

## Supported external setups

| Hosting | `model` example | `base_url` |
|---------|-----------------|------------|
| LiteLLM proxy | `openai/gpt-4o-mini` | `http://localhost:4000` |
| Ollama | `ollama/qwen3:4b` | `http://localhost:11434` |
| vLLM / SGLang | `openai/your-model` | `http://localhost:8000/v1` |
| OpenAI | `gpt-4o-mini` | (omit or `https://api.openai.com/v1`) |

Install: `uv sync --extra litellm`

## Voice teams

Each team member has its own `llm` — responder can use a fast model while `context_agent` uses a smarter one. See `examples/orchestration/voice_team_support.yaml`.
