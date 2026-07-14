# Nexus media model servers

Nexus can run **STT, TTS, VAD, and LID** as separate gRPC servers. The agent runtime connects through lightweight client adapters (`provider: nexus_server`). **LLM is not hosted here** — use [liteLLM](llm-litellm.md) for all text and voice agents.

## Quick start

```bash
# Install gRPC client (agent side)
uv sync --extra grpc

# Install GPU engines (server side, optional for production)
uv sync --extra server

# Start mock servers for local dev
uv run python -m nexus.server up -c examples/servers.yaml

# Check health
uv run python -m nexus.server health -c examples/servers.yaml
```

## Configuration

### `servers.yaml` (or manifest `servers:` block)

| Field | Required? | Default | What it does |
|-------|-----------|---------|--------------|
| `kind` | Yes | — | `stt`, `tts`, `vad`, or `lid` |
| `engine` | Yes | — | Plugin id: `mock`, `conformer`, `parler`, `silero`, `faster_whisper` |
| `host` | No | `127.0.0.1` | Bind address |
| `port` | Yes | — | gRPC port |
| `device` | No | — | `cpu`, `cuda`, `cuda:0`, etc. |
| `replicas` | No | `1` | TTS replica count for concurrent synthesis |
| `extra` | No | `{}` | Engine-specific options (`model_id`, `decoding`, …) |

### Agent manifest references

```yaml
servers:
  indic_stt:
    kind: stt
    engine: conformer
    port: 50051

agents:
  voice_agent:
    stt:
      provider: nexus_server
      server_ref: indic_stt
    tts:
      provider: nexus_server
      server_ref: indic_tts
```

Or point directly: `base_url: 127.0.0.1:50051`.

## Transport

| Leg | Protocol |
|-----|----------|
| Browser → Agent | WebSocket PCM16 |
| Agent → Media servers | gRPC (bidi for STT/VAD/TTS, unary for LID) |
| Agent → LLM | HTTP via liteLLM |

## Tenant context

`RunContext` (`tenant_id`, `user_id`, `session_id`) is sent as gRPC metadata on every media call. Optional per-tenant server pools map tenants to dedicated GPU endpoints via `ServerRegistry.register_tenant_pool()`.

## CLI

```bash
uv run python -m nexus.server up -c servers.yaml       # start all
uv run python -m nexus.server up -c servers.yaml --only indic_stt
uv run python -m nexus.server health -c servers.yaml
uv run python -m nexus.server status -c servers.yaml
```

## Proto regeneration

After editing `nexus/server/proto/media.proto`:

```bash
uv run python -m grpc_tools.protoc \
  -I nexus/server/proto \
  --python_out=nexus/server/proto \
  --grpc_python_out=nexus/server/proto \
  nexus/server/proto/media.proto
```

Then fix the import in `media_pb2_grpc.py` to `from nexus.server.proto import media_pb2 as media__pb2`.
