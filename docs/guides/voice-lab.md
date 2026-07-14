# Voice Lab — real browser testing

The **Voice Lab** is a full-duplex browser UI for testing the Nexus voice stack end-to-end with **real** media servers and **liteLLM** — not mocks.

## What you get

- Mic button → live conversation (VAD → STT → agent → TTS)
- Audio playback of TTS responses
- Barge-in support (full duplex)
- Settings panel showing env config + media server health
- Event log for debugging

## Prerequisites

1. **LLM** — any endpoint liteLLM can reach (LiteLLM proxy, Ollama, vLLM, OpenAI):
   ```bash
   # Example: Ollama
   ollama serve
   # In .env: LITELLM_BASE_URL=http://localhost:11434  VOICE_LLM_MODEL=ollama/qwen3:4b
   ```

2. **Media servers** — gRPC STT/TTS/VAD (GPU recommended for conformer/parler):
   ```bash
   uv sync --extra server --extra grpc
   ```

3. **Copy and edit env**:
   ```bash
   cp .env.example .env
   ```

## Quick start (one command)

```bash
./scripts/run_voice_lab.sh
```

Opens http://localhost:8787 — allow microphone, click 🎤.

## Manual start

Terminal 1 — media servers:
```bash
uv run python -m nexus.server up -c examples/servers.yaml
uv run python -m nexus.server health -c examples/servers.yaml
```

Terminal 2 — voice lab UI:
```bash
uv run --extra fastapi --extra realtime --extra litellm --extra grpc \
  uvicorn examples.voice_lab:app --host 0.0.0.0 --port 8787
```

## Key env vars

| Variable | Purpose | Example |
|----------|---------|---------|
| `LITELLM_BASE_URL` | LLM endpoint | `http://localhost:4000` |
| `VOICE_LLM_MODEL` | Voice agent model | `ollama/qwen3:4b` |
| `STT_ENGINE` | STT server engine | `conformer` or `mock` |
| `TTS_ENGINE` | TTS server engine | `parler` or `mock` |
| `STT_DEVICE` / `TTS_DEVICE` | GPU/CPU | `cuda`, `cpu` |
| `VAD_PROVIDER` | Agent VAD | `energy` (local) or `nexus_server` |
| `NEXUS_VOICE_MANIFEST` | Agent YAML | `examples/orchestration/voice_grpc.yaml` |

## CPU-only smoke test

Set in `.env`:
```
STT_ENGINE=mock
TTS_ENGINE=mock
VAD_ENGINE=mock
LITELLM_BASE_URL=http://localhost:11434
VOICE_LLM_MODEL=ollama/qwen3:4b
```

Still uses the real pipeline and WebSocket path; only model weights are lightweight mocks.

## APIs

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Browser UI |
| `GET /api/status` | Config + server health |
| `GET /api/health` | Preflight (503 if media down) |
| `POST /v1/realtime/sessions` | Create session |
| `WS /v1/realtime/ws/{id}` | Full-duplex voice |

See also: [model-servers.md](model-servers.md), [llm-litellm.md](llm-litellm.md).
