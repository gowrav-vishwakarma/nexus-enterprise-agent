# Examples index

**Who this is for:** Developers looking for runnable code beyond the getting-started guides.

Not sure which example fits your use case? See the [pipelines guide](guides/pipelines.md) for a decision table (text, multi-agent, cascaded voice, S2S, channels) with links to every row below.

## Key terms

- **Example** — A script or config in the `examples/` folder you can run or copy.
- **Fixture** — Test data under `tests/fixtures/` used by pytest.

## Starter templates

Whole-application skeletons to copy into a new project, rather than single-feature
examples. Each one runs as-is.

| Template | Shape | Start it |
|----------|-------|----------|
| [templates/saas-chat](../templates/saas-chat) | Multi-tenant chat API, tenant per request | `uv run uvicorn templates.saas-chat.main:app` |
| [templates/personal-agent](../templates/personal-agent) | One operator, durable memory, terminal loop | `uv run python templates/personal-agent/main.py` |
| [templates/background-worker](../templates/background-worker) | Scheduled agents with nobody waiting | `uv run python templates/background-worker/main.py --once` |
| [templates/voice-agent](../templates/voice-agent) | Points at the realtime voice examples below | — |

## Orchestration (YAML) — text agents

| Path | What you will learn |
|------|---------------------|
| [examples/orchestration/research_team.yaml](../examples/orchestration/research_team.yaml) | Supervisor + nested pipeline team; agents select toolsets |
| [examples/orchestration/research_team_prompts.py](../examples/orchestration/research_team_prompts.py) | PROMPTS dict, Jinja templates |
| [examples/orchestration/run_team.py](../examples/orchestration/run_team.py) | CLI to load manifest, build a ToolRegistry with add_toolset(), and run |
| [examples/orchestration/run_team_python.py](../examples/orchestration/run_team_python.py) | Same research team built in Python (`AgentGroupConfig` + `AgentOrchestrator`) |

```bash
uv run python examples/orchestration/run_team.py "Your question here"
uv run python examples/orchestration/run_team_python.py "Your question here"
```

Annotated references (not runnable as-is):

- [assets/complete-manifest.annotated.yaml](assets/complete-manifest.annotated.yaml)
- [assets/research_team_prompts.annotated.py](assets/research_team_prompts.annotated.py)
- [assets/complete-run.annotated.py](assets/complete-run.annotated.py)

## SaaS API — text

| Path | What you will learn |
|------|---------------------|
| [examples/nexus_saas_api.py](../examples/nexus_saas_api.py) | FastAPI multi-tenant app, plan gating, streaming, `/v1/chat/vision` |

Guide: [guides/saas-example.md](guides/saas-example.md).

## Voice — canonical (gRPC + Voice Lab)

| Path | What you will learn |
|------|---------------------|
| [examples/orchestration/voice_grpc.yaml](../examples/orchestration/voice_grpc.yaml) | Cascaded voice manifest with gRPC media servers + liteLLM |
| [examples/orchestration/voice_grpc_prompts.py](../examples/orchestration/voice_grpc_prompts.py) | Voice system prompt (`PROMPTS["voice_system"]`) |
| [examples/orchestration/voice_grpc_tools.py](../examples/orchestration/voice_grpc_tools.py) | Flat `@tool` functions + toolset registration helper |
| [examples/servers.yaml](../examples/servers.yaml) | gRPC STT/TTS/VAD/LID server config |
| [examples/voice_lab.py](../examples/voice_lab.py) | FastAPI + `RealtimeRuntime` + WebSocket browser UI |
| [scripts/run_voice_lab.sh](../scripts/run_voice_lab.sh) | One-command launcher (media servers + UI) |

```bash
./scripts/run_voice_lab.sh
# Opens http://localhost:8787
```

Guides: [guides/voice-lab.md](guides/voice-lab.md), [guides/model-servers.md](guides/model-servers.md). Full config reference: [reference/server.md](reference/server.md).

## Voice — alternates

| Path | What you will learn |
|------|---------------------|
| [examples/orchestration/ivr_support.yaml](../examples/orchestration/ivr_support.yaml) | Half-duplex IVR voice agent (cascaded) |
| [examples/realtime_ivr_server.py](../examples/realtime_ivr_server.py) | Run the IVR pipeline locally (no keys needed) |
| [examples/orchestration/voice_team_support.yaml](../examples/orchestration/voice_team_support.yaml) | Voice team: responder + context agent |
| [examples/orchestration/voice_s2s_local.yaml](../examples/orchestration/voice_s2s_local.yaml) | Speech-to-speech via Moshi or Human-1 |
| [examples/realtime_s2s_ui.py](../examples/realtime_s2s_ui.py) | Full-duplex speech-to-speech browser UI (Moshi) |
| [examples/realtime_saas_api.py](../examples/realtime_saas_api.py) | Production SaaS: sessions, voice WS, Twilio/SIP, channels |

Reference: [reference/realtime-agents.md](reference/realtime-agents.md).

```bash
uv run python examples/realtime_ivr_server.py "I want to pay my bill"
```

## Python API (annotated)

| Path | What you will learn |
|------|---------------------|
| [assets/complete-agent.annotated.py](assets/complete-agent.annotated.py) | Every AgentConfig and AgentRunner parameter |
| [guides/porting-from-langgraph.md](guides/porting-from-langgraph.md) | Port a stateful LangGraph support agent to Nexus (side-by-side) |

Walkthrough: [getting-started-python.md](getting-started-python.md).

## Porting from other frameworks

| Path | What you will learn |
|------|---------------------|
| [guides/porting-from-langgraph.md](guides/porting-from-langgraph.md) | Stateful agents: checkpoint state, HITL, supervisor team vs LangGraph StateGraph |

LangGraph is not installed in this repo; the guide uses illustrative LangGraph snippets and runnable Nexus code.

## Test fixtures (orchestration)

Under `tests/fixtures/orchestration/`:

| File | What it tests |
|------|---------------|
| `basic.yaml` | Minimal single agent |
| `nested.yaml` | Nested groups |
| `parallel.yaml` | Parallel pattern (runs members concurrently) |
| `cycle.yaml` | Cycle detection error |

## Next steps

- [Getting started (YAML)](getting-started.md)
- [Voice Lab guide](guides/voice-lab.md)
- [Documentation index](index.md)
