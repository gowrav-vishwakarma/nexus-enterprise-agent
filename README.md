# Nexus

**Enterprise-ready agent framework.** Describe agents in config. Wire who is calling and where data lives at run time. Call `run()`.

No global LLM settings. No shared agent singleton. Built for multi-tenant SaaS apps.

> **Beta — under active development.** See [NEXUS_AGENT_PRD.md](NEXUS_AGENT_PRD.md) for the design spec.

## Why Nexus?

- **SaaS-native** — tenant, user, API keys, and storage passed per request
- **Context-first (RCS)** — compresses old tool results inline; no extra LLM calls
- **Config-driven** — YAML manifests for teams; Python for wiring and tools
- **Provider-agnostic** — bring your own model; pluggable storage
- **Voice** — gRPC media servers + WebSocket browser UI on the same agent core

---

## Install

Published on PyPI as [`nexus-enterprise-agent`](https://pypi.org/project/nexus-enterprise-agent/). Import as `nexus`.

```bash
pip install nexus-enterprise-agent
# or
uv add nexus-enterprise-agent
```

| Extra | Adds |
|-------|------|
| `sqlite`, `postgres`, `redis`, `file` | Storage adapters |
| `openai`, `anthropic`, `gemini`, `litellm`, `groq`, `ollama` | LLM clients |
| `fastapi` | FastAPI + WebSocket helpers |
| `realtime` | Voice transports (`websockets`, `httpx`) |
| `grpc` | gRPC client for media servers |
| `server` | GPU media server engines (torch, transformers) |
| `moshi` | Speech-to-speech client (Moshi/Human-1) |

```bash
pip install "nexus-enterprise-agent[sqlite,litellm,fastapi,realtime,grpc]"
```

**Contributors:**

```bash
git clone https://github.com/gowrav-vishwakarma/nexus-enterprise-agent.git
cd nexus-enterprise-agent
uv sync --extra sqlite --extra file
cp .env.example .env   # set your LLM API key
```

---

## Text agents (YAML)

Three files: manifest, prompts module, short runner script.

```bash
uv run python examples/orchestration/run_team.py "Analyze Q4 revenue"
```

- Manifest: [examples/orchestration/research_team.yaml](examples/orchestration/research_team.yaml)
- Prompts: [examples/orchestration/research_team_prompts.py](examples/orchestration/research_team_prompts.py)

**Python API** (same agents, built in code):

```python
from nexus import AgentRunner, RunContext
result = await AgentRunner(config=agent_config, tool_registry=registry, run_context=ctx).run("Hello")
```

Walkthrough: [docs/getting-started.md](docs/getting-started.md) (YAML) · [docs/getting-started-python.md](docs/getting-started-python.md) (Python)

---

## Voice agents (gRPC + Voice Lab)

Cascaded voice: VAD → STT → LLM → TTS over gRPC media servers. Browser connects via WebSocket.

```bash
./scripts/run_voice_lab.sh
```

Opens http://localhost:8787 — allow microphone, click the mic button.

- Manifest: [examples/orchestration/voice_grpc.yaml](examples/orchestration/voice_grpc.yaml)
- Media servers: [examples/servers.yaml](examples/servers.yaml)
- UI: [examples/voice_lab.py](examples/voice_lab.py)

**Python API** (same manifest, custom transport):

```python
from nexus.realtime.runtime import RealtimeRuntime
from nexus.realtime import RealtimeSession
from nexus.realtime.transport.websocket import WebSocketTransport

runtime = RealtimeRuntime.from_manifest(manifest, run_context=ctx)
pipeline = runtime.build_pipeline("voice_grpc")
session = RealtimeSession(pipeline, WebSocketTransport(websocket), session_id=sid)
await session.run_audio()
```

Guide: [docs/guides/voice-lab.md](docs/guides/voice-lab.md) · [docs/guides/model-servers.md](docs/guides/model-servers.md)

---

## Learn more

Full docs: **[docs/index.md](docs/index.md)**

| Topic | Doc |
|-------|-----|
| Architecture | [docs/architecture.md](docs/architecture.md) |
| YAML walkthrough | [docs/getting-started.md](docs/getting-started.md) |
| Python API | [docs/getting-started-python.md](docs/getting-started-python.md) |
| Voice Lab | [docs/guides/voice-lab.md](docs/guides/voice-lab.md) |
| gRPC media servers | [docs/guides/model-servers.md](docs/guides/model-servers.md) |
| Pipelines (text, voice, teams) | [docs/guides/pipelines.md](docs/guides/pipelines.md) |
| Voice / channels reference | [docs/reference/realtime-agents.md](docs/reference/realtime-agents.md) |
| SaaS example | [docs/guides/saas-example.md](docs/guides/saas-example.md) |
| All examples | [docs/examples.md](docs/examples.md) |
