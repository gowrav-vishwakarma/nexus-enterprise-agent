# Nexus media model servers

Nexus can run **STT, TTS, VAD, and LID** as separate gRPC servers. The agent runtime connects through lightweight client adapters (`provider: nexus_server`). **LLM is not hosted here** — use [liteLLM](llm-litellm.md) for all text and voice agents.

**Full parameter reference:** [server.md](../reference/server.md) — every `servers:` field, every agent `server_ref`, examples, and the Voice Lab two-YAML setup.

## Key terms

- **`server_ref`** — Label on the agent (`stt.server_ref: indic_stt`) that points at one entry in `servers:`.
- **`servers:`** — YAML map that defines host, port, engine, and model options for each media process.
- **Registry** — Resolves `server_ref` → `host:port` at runtime.

## Quick start

```bash
# Install gRPC client (agent side)
uv sync --extra grpc

# Install GPU engines (server side, optional for production)
uv sync --extra server

# Start all media servers (STT, TTS, VAD, LID)
uv run python -m nexus.server up -c examples/servers.yaml

# Check health
uv run python -m nexus.server health -c examples/servers.yaml
```

Default ports: STT `50051`, TTS `50052`, VAD `50053`, LID `50054`.

## How `server_ref` connects to a host

```yaml
servers:
  whisper_lid:                    # ① You define a label + endpoint
    kind: lid
    engine: faster_whisper
    host: 127.0.0.1
    port: 50054

agents:
  voice_grpc:
    lid:
      provider: nexus_server
      server_ref: whisper_lid     # ② Agent points at the label
```

At runtime: `whisper_lid` → registry → `127.0.0.1:50054` → `GrpcLID` gRPC client → `LidService.DetectLanguage`.

Labels are **arbitrary** — `indic_stt`, `my_lid`, `gpu_stt_west` all work. Only the string in `server_ref` must match the key under `servers:`.

## Voice Lab: two YAML files

| File | Purpose |
|------|---------|
| `examples/orchestration/voice_grpc.yaml` | Agent config + `servers:` for **connection** (registry) |
| `examples/servers.yaml` | **Starts** gRPC processes (`run_voice_lab.sh`) |

Keep server **names and ports identical** in both files, or use one file for both:

```bash
export NEXUS_SERVERS_CONFIG=examples/orchestration/voice_grpc.yaml
./scripts/run_voice_lab.sh
```

Details: [server.md — Two YAML files](../reference/server.md#two-yaml-files-in-voice-lab-important).

## Configuration summary

### `servers:` entry (`ModelServerSpec`)

| Field | Required? | Default | What it does |
|-------|-----------|---------|--------------|
| `kind` | Yes | — | `stt`, `tts`, `vad`, `lid` |
| `engine` | Yes | — | `mock`, `conformer`, `parler`, `silero`, `faster_whisper`, … |
| `host` | No | `127.0.0.1` | Bind / connect address |
| `port` | Yes | — | gRPC port |
| `device` | No | — | `cpu`, `cuda`, `cuda:0`, … |
| `replicas` | No | `1` | TTS concurrent synthesis pools |
| `sample_rate` | No | — | Native Hz (TTS — match agent `tts.sample_rate`) |
| `extra` | No | `{}` | Engine options (`model_id`, `decoding`, `model_size`, …) |

### Agent references

```yaml
agents:
  voice_agent:
    stt: {provider: nexus_server, server_ref: indic_stt, language: hi}
    tts: {provider: nexus_server, server_ref: indic_tts, sample_rate: 44100}
    vad: {provider: energy}                    # or nexus_server + server_ref
    lid: {provider: nexus_server, server_ref: whisper_lid, fallback_language: hi}
```

Or point directly without registry: `base_url: 127.0.0.1:50051`.

## Transport

| Leg | Protocol |
|-----|----------|
| Browser → Agent | WebSocket PCM16 |
| Agent → Media servers | gRPC (bidi for STT/VAD/TTS, unary for LID) |
| Agent → LLM | HTTP via liteLLM |

## Per-turn language (LID)

When the agent has a `lid:` block, each utterance is language-identified before STT. Detected language is passed to the STT server; reply language drives LLM prompts and TTS. See [realtime-agents.md](../reference/realtime-agents.md) and [server.md — lid block](../reference/server.md#lid--per-turn-language-detection-optional).

## Tenant context

`RunContext` (`tenant_id`, `user_id`, `session_id`) is sent as gRPC metadata on every media call. Optional per-tenant server pools: `ServerRegistry.register_tenant_pool()`.

## CLI

```bash
uv run python -m nexus.server up -c servers.yaml       # start all
uv run python -m nexus.server up -c servers.yaml --only indic_stt
uv run python -m nexus.server health -c servers.yaml
uv run python -m nexus.server status -c servers.yaml
```

## Browser testing

Use the [Voice Lab](voice-lab.md) (`./scripts/run_voice_lab.sh`) for full-duplex browser testing with real media servers and env-driven config.
