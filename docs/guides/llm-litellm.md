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

  voice_grpc:
    modality: voice_cascaded
    agent:
      llm: *llm_fast
      tool_plugins: [voice_tools]
```

## Reasoning models, `extra_body`, and headers

Any key under `default_params` is passed straight through to the provider on every
call. This is how you tune reasoning ("thinking") models and pass engine-specific
switches or HTTP headers — no code changes needed.

**Thinking is disabled at the source by default.** Reasoning models like Qwen3
otherwise spend the first few seconds (and much of the token budget) emitting a
`<think>…</think>` block before any speakable text, which wrecks voice latency. For
OpenAI-compatible proxies Nexus automatically sets
`extra_body.chat_template_kwargs.enable_thinking = false`. As a final safety net,
the cascaded voice pipeline also strips any `<think>…</think>` that still leaks
through, so reasoning is never spoken.

To make it explicit, override it, or add engine-specific switches, set them yourself
— anything you provide wins over the auto-default:

```yaml
defaults:
  llm_fast: &llm_fast
    provider: litellm
    model: ${ENV:VOICE_LLM_MODEL|ollama/qwen3:4b}
    base_url: ${ENV:LITELLM_BASE_URL|http://localhost:4000}
    api_key: ${ENV:LITELLM_API_KEY|}
    default_params:
      max_tokens: 400
      temperature: 0.4
      extra_body:
        chat_template_kwargs:
          enable_thinking: false   # vLLM / SGLang / Qwen chat template
        # think: false             # Ollama-native switch (if your proxy forwards it)
        # reasoning_effort: low    # gpt-oss / reasoning-effort models
    extra_headers:
      x-my-route: voice            # forwarded on every request
```

To **re-enable** reasoning for a smart (non-voice) agent, set
`enable_thinking: true` in that agent's own `default_params.extra_body`.

Note on routing: **every provider goes through one `LiteLLMAdapter`**. Set
`VOICE_LLM_MODEL` (or `NEXUS_LLM_MODEL`) to the **exact model name registered on
your proxy** — e.g. `openai/qwen`, not `qwen`. When `base_url` is set, Nexus
only adds litellm's required `litellm_proxy/` transport prefix internally; your
env value is unchanged. `extra_body` and `extra_headers` pass through on every path.

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
