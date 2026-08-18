# Getting started with YAML orchestration

**Who this is for:** Developers who want the fastest path to a working multi-agent team using a config file.

## Key terms

- **YAML** — A human-readable text format for configuration files.
- **Manifest** — Your YAML file that lists agents, teams, storage, and tool plugins.
- **Prompts module** — A Python file beside the YAML that holds prompt template strings.
- **Orchestration runtime** — The object that loads the manifest and runs your team.
- **Run context** — Who is calling (customer, user) and which chat thread this is.

## What you will build

Three files:

1. `team.yaml` — what agents exist and how they connect
2. `team_prompts.py` — how they speak (prompt templates)
3. A short Python script — load manifest, set run context, call `run()`

The repo already includes a working example at [examples/orchestration/](../examples/orchestration/).

## Step 1: Install

```bash
uv sync --extra sqlite --extra litellm
```

Copy [.env.example](../.env.example) to `.env` and set your LLM API key:

```env
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-4o-mini
```

Nexus does not read LLM keys from the environment by itself. The YAML manifest uses `${ENV:OPENAI_API_KEY}` so **your config file** pulls from the environment.

## Step 2: Understand the manifest

Open [examples/orchestration/research_team.yaml](../examples/orchestration/research_team.yaml).

A manifest has:

- `root` — which agent or team to run (required)
- `agents` — single agents with LLM, persona, and optional tools
- `groups` — teams (supervisor or pipeline pattern)
- `defaults` — shared LLM and turn limits
- `storage` — where chat history is saved
- `plugins` — optional Python classes that provide tools (legacy plugin path)
- `agents.<name>.toolset` — which named toolset the agent may use

For every field with defaults, see the annotated copy: [assets/complete-manifest.annotated.yaml](assets/complete-manifest.annotated.yaml).

## Step 3: Write prompt templates

Open [assets/research_team_prompts.annotated.py](assets/research_team_prompts.annotated.py) (field-by-field comments) or the runnable [examples/orchestration/research_team_prompts.py](../examples/orchestration/research_team_prompts.py).

Your prompts module must define:

```python
PROMPTS = {
    "researcher_system": "You are {{ role }}. Goal: {{ goal }}",
}
```

In YAML you reference a key:

```yaml
persona:
  role: Researcher
  goal: Gather facts
  prompt: researcher_system
  prompt_args:
    domain: finance
```

**Single render (each LLM turn):** The framework stores the raw template at load time, then renders all variables together — `role`, `goal`, `prompt_args`, `tenant_id`, `user_memory`, `summary_text`, and `current_date`. See [guides/prompts-jinja.md](guides/prompts-jinja.md).

## Step 4: Run

```bash
uv run python examples/orchestration/run_team.py "Analyze Q4 revenue"
```

Or from Python:

```python
import asyncio
from nexus import OrchestrationManifest, OrchestrationRuntime, RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry


@tool(name="web_search")
def web_search(query: str) -> str:
    return f"Results for {query}"


@tool(name="database_query")
def database_query(sql: str) -> str:
    return f"Rows for {sql}"


async def main():
    registry = ToolRegistry()
    registry.add_toolset("researcher", [web_search])
    registry.add_toolset("analyst", [database_query])

    manifest = OrchestrationManifest.load("examples/orchestration/research_team.yaml")
    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        run_context=RunContext(
            tenant_id="demo-tenant",
            user_id="demo-user",
            session_id="chat-1",  # set before building runtime for teams
        ),
        tool_registry=registry,
    )
    result = await runtime.run("Analyze Q4 revenue")
    print(result.final_response)

asyncio.run(main())
```

Every `OrchestrationRuntime` parameter is explained in [assets/complete-run.annotated.py](assets/complete-run.annotated.py).

## Step 5: Set run context for teams

For multi-agent teams, set `session_id` on `RunContext` **before** you call `OrchestrationRuntime.from_manifest()`.

Each team member saves chat history under `{session_id}_{member_name}` (for example `chat-1_researcher`).

## Env interpolation in YAML

Use `${ENV:VAR}` or `${ENV:VAR|default}` in any YAML string:

```yaml
llm:
  model: ${ENV:OPENAI_MODEL|gpt-4o}
  api_key: ${ENV:OPENAI_API_KEY}
```

## Toolsets

Tools are grouped into named packs on a `ToolRegistry`. Build the registry in Python and pass it to `from_manifest()`; then each agent selects the pack it needs.

```python
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry


@tool(name="web_search")
def web_search(query: str) -> str:
    return f"Results for {query}"


registry = ToolRegistry()
registry.add_toolset("researcher", [web_search])
```

```yaml
agents:
  researcher:
    toolset: researcher
```

`toolset` can be a single name or a list (`[researcher, analyst]`). `None` means the agent sees every registered tool. For plan-tier gating, define toolsets per tier and set `toolset` from your config factory. Details: [reference/tools.md](reference/tools.md).

The legacy plugin path still works: declare `plugins:` in YAML and use `tool_plugins:` on an agent. A pre-built `ToolRegistry` passed to `from_manifest()` and YAML `plugins:` can be combined.

## When to use YAML vs Python

| Use YAML orchestration when | Use Python API when |
|----------------------------|---------------------|
| Ops or product owns agent definitions | You build config per tenant/plan in code |
| You want env-based secrets in config | You need dynamic config without files |
| You want one file to describe a whole team | You prefer full programmatic control |

Python walkthrough: [getting-started-python.md](getting-started-python.md).

## Voice agents (optional)

Nexus supports text agents first, but the same manifest can add voice via
`RealtimeRuntime`. The canonical path is **gRPC media servers + Voice Lab**:

- **Cascaded voice (STT → LLM → TTS)** — modular stages over gRPC; good for local models and browser testing.
- **Speech-to-speech (S2S)** — one realtime audio model with bridged tools.

### YAML way

The manifest declares media servers and a voice agent that references them:

```yaml
servers:
  indic_stt:
    kind: stt
    engine: conformer
    port: 50051
  indic_tts:
    kind: tts
    engine: parler
    port: 50052
    sample_rate: 44100

agents:
  voice_grpc:
    modality: voice_cascaded
    duplex: full
    stt: {provider: nexus_server, server_ref: indic_stt, language: hi}
    tts: {provider: nexus_server, server_ref: indic_tts, sample_rate: 44100}
    agent:
      llm: *llm_fast
      persona: {prompt: voice_system}
```

Full example: [examples/orchestration/voice_grpc.yaml](../examples/orchestration/voice_grpc.yaml).

### Python way

```python
from nexus.realtime.runtime import RealtimeRuntime
from nexus.realtime import RealtimeSession
from nexus.realtime.transport.websocket import WebSocketTransport

manifest = OrchestrationManifest.load("examples/orchestration/voice_grpc.yaml")
runtime = RealtimeRuntime.from_manifest(manifest, run_context=ctx)
pipeline = runtime.build_pipeline("voice_grpc")
session = RealtimeSession(pipeline, WebSocketTransport(websocket), session_id=sid)
await session.run_audio()
```

### Quick browser test

```bash
./scripts/run_voice_lab.sh
```

Opens http://localhost:8787. Guide: [guides/voice-lab.md](guides/voice-lab.md).

For pipeline choice (cascaded vs S2S vs IVR), see [guides/pipelines.md](guides/pipelines.md) and [reference/realtime-agents.md](reference/realtime-agents.md).

## Next steps

- [Pipelines guide](guides/pipelines.md) — text, multi-agent, voice, channels: which to use
- [Runtime control](guides/runtime-control.md) — take charge when tools or tenant state change
- [Manifest schema reference](reference/manifest-schema.md)
- [Architecture](architecture.md)
- [Multi-agent patterns](reference/multi-agent.md)
- [SaaS example guide](guides/saas-example.md)
- [RAG](reference/rag.md) — opt-in document retrieval
- [Memory](reference/memory.md) — user facts across chats
