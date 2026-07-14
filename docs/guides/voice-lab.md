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

   For the Indic **Parler** TTS engine, install it separately — it can't go in
   the lockfile because its dependencies pin `protobuf<5`, which clashes with the
   gRPC stubs (`protobuf>=5`). Install then repin:
   ```bash
   uv pip install parler-tts
   uv pip install "protobuf>=5.26"
   ```
   The model weights (`ai4bharat/indic-parler-tts`) download automatically on
   first synthesis and are cached under `~/.cache/huggingface`. `run_voice_lab.sh`
   does this automatically when `TTS_ENGINE=parler`.

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

## Customising the agent

The manifest `examples/orchestration/voice_grpc.yaml` ships with three companion
pieces you can edit:

- **System prompt** — `examples/orchestration/voice_grpc_prompts.py` defines
  `PROMPTS["voice_system"]`. The agent references it via `persona.prompt:
  voice_system`. Edit the string/callable there instead of inlining prompt text
  in YAML.
- **Tools** — `examples/orchestration/voice_grpc_tools.py` defines a
  `VoiceToolsPlugin` (a dummy `get_current_datetime` tool). It is registered in
  the manifest `plugins:` block and enabled per-agent via `agent.tool_plugins:
  [voice_tools]`. Add your own `@tool` methods to expose more capabilities.

### Server names and swapping engines

The keys under `servers:` (`indic_stt`, `indic_tts`, `silero_vad`) are arbitrary
labels — the agent only cares about the `server_ref` that points at them. To use
an English TTS instead, add another server (e.g. `en_tts` with `engine: kokoro`)
and set the agent's `tts.server_ref: en_tts`. A commented example is included in
the manifest.

### Sample rate

TTS output rate is tunable in YAML so playback isn't pitch-shifted. Set it in two
places that must agree: the server's `sample_rate` (native engine rate) and the
agent's `tts.sample_rate` (the rate sent to the browser). Both default to
`${ENV:TTS_SAMPLE_RATE|44100}` for Parler; use `24000` for kokoro/mock.

## Python API (coding way)

Wire a voice pipeline in code the same way Voice Lab does:

```python
from nexus import OrchestrationManifest, RunContext
from nexus.realtime.runtime import RealtimeRuntime
from nexus.realtime import RealtimeSession
from nexus.realtime.transport.websocket import WebSocketTransport

manifest = OrchestrationManifest.load("examples/orchestration/voice_grpc.yaml")
run_context = RunContext(tenant_id="lab", user_id="tester", session_id=session_id)
runtime = RealtimeRuntime.from_manifest(manifest, run_context=run_context)
pipeline = runtime.build_pipeline("voice_grpc")
session = RealtimeSession(pipeline, WebSocketTransport(websocket), session_id=session_id)
await session.run_audio()
```

See [examples/voice_lab.py](../../examples/voice_lab.py) for the full FastAPI app.

## APIs

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Browser UI |
| `GET /api/status` | Config + server health |
| `GET /api/health` | Preflight (503 if media down) |
| `POST /v1/realtime/sessions` | Create session |
| `WS /v1/realtime/ws/{id}` | Full-duplex voice |

See also: [model-servers.md](model-servers.md), [llm-litellm.md](llm-litellm.md).
