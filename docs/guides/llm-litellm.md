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
    # Modern path: select a toolset defined on a pre-built ToolRegistry.
    toolset: erp_tools
    # Legacy plugin-namespace path:
    # tool_plugins: [erp_tools]

  voice_grpc:
    modality: voice_cascaded
    agent:
      llm: *llm_fast
      # Modern path: select a toolset defined on a pre-built ToolRegistry.
      toolset: voice_tools
      # Legacy plugin-namespace path:
      # tool_plugins: [voice_tools]
```

## Reasoning models, `extra_body`, and headers

Any key under `default_params` is passed straight through to the provider on every
call. This is how you tune reasoning ("thinking") models and pass engine-specific
switches or HTTP headers — no code changes needed.

**Thinking follows your model's own setting by default.** Nexus does not turn it on
or off behind your back. When a model does think, Nexus streams it as `reasoning`
events, separate from the answer — see [streaming.md](../reference/streaming.md#reasoning-thinking).

**Turn it off for voice.** Reasoning models like Qwen3 otherwise spend the first few
seconds (and much of the token budget) emitting a `<think>…</think>` block before any
speakable text, which wrecks voice latency. Set `enable_thinking: false` on the voice
agent's LLM config, and Nexus sets `extra_body.chat_template_kwargs.enable_thinking`
for you. As a final safety net, the cascaded voice pipeline also strips any
`<think>…</think>` that still leaks into the text, so reasoning is never spoken.

Anything you set in `default_params.extra_body` wins over `enable_thinking`, so you
can always spell the switch out yourself or add engine-specific ones:

```yaml
defaults:
  llm_fast: &llm_fast
    provider: litellm
    model: ${ENV:VOICE_LLM_MODEL|ollama/qwen3:4b}
    base_url: ${ENV:LITELLM_BASE_URL|http://localhost:4000}
    api_key: ${ENV:LITELLM_API_KEY|}
    enable_thinking: false         # voice: no <think> block before the first word
    default_params:
      max_tokens: 400
      temperature: 0.4
      extra_body:
        # chat_template_kwargs:
        #   enable_thinking: false # same switch, spelled out — wins over the above
        # think: false             # Ollama-native switch (if your proxy forwards it)
        # reasoning_effort: low    # gpt-oss / reasoning-effort models
    extra_headers:
      x-my-route: voice            # forwarded on every request
```

For a smart (non-voice) agent, leave `enable_thinking` unset to keep the model's own
behaviour, or set it to `true` to ask for reasoning explicitly.

A self-hosted vLLM or SGLang deployment only reports reasoning separately when it was
started with a matching `--reasoning-parser` (e.g. `--reasoning-parser qwen3`). Without
that flag the `<think>` block stays inside the normal content and arrives as plain text.

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
