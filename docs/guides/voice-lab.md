# Voice Lab — real browser testing

The **Voice Lab** is a full-duplex browser UI for testing the Nexus voice stack end-to-end with **real** media servers and **liteLLM** — not mocks.

**Media server configuration (full reference):** [server.md](../reference/server.md) — every `server_ref`, `servers:` field, port, engine, LID, and the two-YAML setup explained with examples.

## Key terms

- **`server_ref`** — Name that links an agent stage (STT, TTS, LID) to a server defined under `servers:`.
- **Manifest** — `voice_grpc.yaml` — agent persona, tools, and connection map for media servers.
- **Servers config** — `examples/servers.yaml` — file used to **start** gRPC processes.

## What you get

- Mic button → live conversation (VAD → STT → agent → TTS)
- Audio playback of TTS responses
- Barge-in support (full duplex) — mic stays open while the assistant speaks;
  start talking to interrupt. Browser echo cancellation + a short mute after
  playback ends reduce speaker echo false triggers
- Settings panel showing env config + media server health
- Event log for debugging

## Prerequisites

1. **LLM** — any endpoint liteLLM can reach (LiteLLM proxy, Ollama, vLLM, OpenAI):
   ```bash
   # Example: Ollama
   ollama serve
   # In .env: LITELLM_BASE_URL=http://localhost:11434  VOICE_LLM_MODEL=ollama/qwen3:4b
   ```

2. **Media servers** — gRPC STT / TTS / VAD / LID (GPU recommended for conformer/parler):
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
| `LITELLM_API_KEY` | API key for proxy | (empty for local Ollama) |
| `VOICE_LLM_MODEL` | Voice agent model | `ollama/qwen3:4b` |
| `VOICE_LLM_MAX_TOKENS` | Max tokens per reply | `400` |
| `VOICE_LLM_TEMPERATURE` | LLM temperature | `0.4` |
| `NEXUS_LLM_*` | Legacy/SaaS aliases | Mapped to `LITELLM_*` / `VOICE_LLM_MODEL` at startup |
| `STT_ENGINE` | STT server engine | `conformer` or `mock` |
| `TTS_ENGINE` | TTS server engine | `parler` or `mock` |
| `STT_DEVICE` / `TTS_DEVICE` | GPU/CPU | `cuda`, `cpu` |
| `VAD_PROVIDER` | Agent VAD | `energy` (local) or `nexus_server` |
| `LID_ENGINE` / `LID_PORT` / `LID_DEVICE` | LID server | `faster_whisper` / `50054` / `cpu` |
| `VOICE_DEFAULT_LANGUAGE` | Default reply, STT, LID fallback | `en` (set `hi` for Hindi-first) |
| `STT_LANGUAGE` | Legacy alias → `VOICE_DEFAULT_LANGUAGE` | — |
| `NEXUS_SERVERS_CONFIG` | YAML to **start** media processes | `examples/servers.yaml` |
| `NEXUS_VOICE_MANIFEST` | Agent YAML (registry + agent) | `examples/orchestration/voice_grpc.yaml` |

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

### Media servers and `server_ref`

Voice Lab wires four optional gRPC stages. Each uses the same pattern: define under `servers:`, reference with `server_ref`.

| Label (`server_ref`) | Role | Default port | Agent block |
|----------------------|------|--------------|-------------|
| `indic_stt` | Speech-to-text (Indic Conformer) | 50051 | `stt.server_ref` |
| `indic_tts` | Text-to-speech (Indic Parler) | 50052 | `tts.server_ref` |
| `silero_vad` | Voice activity (optional remote VAD) | 50053 | `vad.server_ref` |
| `whisper_lid` | Per-turn language detection | 50054 | `lid.server_ref` |

**Two YAML files must agree** on names and ports:

1. **`examples/orchestration/voice_grpc.yaml`** — `servers:` block + agent `server_ref` values. Voice Lab builds the **connection registry** from here.
2. **`examples/servers.yaml`** — used by `./scripts/run_voice_lab.sh` to **start** listener processes.

If you add `whisper_lid` to the manifest but forget to start it (or use a different port in `servers.yaml`), LID health checks fail and per-turn language switching will not work.

**Single-file setup** — use the manifest for both roles:

```bash
export NEXUS_SERVERS_CONFIG=examples/orchestration/voice_grpc.yaml
./scripts/run_voice_lab.sh
```

**Why labels instead of hard-coded hosts?** Swap engines, point at remote GPUs, or share one STT server across many agents by changing YAML only. See [server.md](../reference/server.md).

**Example — swap TTS to English Kokoro:**

```yaml
servers:
  en_tts:
    kind: tts
    engine: kokoro
    port: 50062
    sample_rate: 24000

agents:
  voice_grpc:
    tts:
      server_ref: en_tts
      sample_rate: 24000
```

A commented `en_tts` example is in the manifest.

### Sample rate

TTS output rate is tunable in YAML so playback isn't pitch-shifted. Set it in two
places that must agree: the server's `sample_rate` (native engine rate) and the
agent's `tts.sample_rate` (the rate sent to the browser). Both default to
`${ENV:TTS_SAMPLE_RATE|44100}` for Parler; use `24000` for kokoro/mock.

## Connect greeting (`initial_response`)

When the manifest sets `initial_response.mode` to `proactive` or `ivr`, the WebSocket
session speaks that greeting at connect. On **full duplex**, listening starts
immediately so the greeting is interruptible (barge-in). On **half duplex** (IVR),
the greeting finishes before the mic is processed. Configure in
[`voice_grpc.yaml`](../../examples/orchestration/voice_grpc.yaml) or
[`ivr_support.yaml`](../../examples/orchestration/ivr_support.yaml).

- `via_llm: false` + `text` — deterministic TTS in `reply_language` (`hi`, `en`, …)
- `via_llm: true` + `llm_trigger` — LLM generates the opening (persona + tools apply; supports hi/en/gu/…)
- IVR mode — use with `duplex: half` and `ivr_menu` plugin; `ivr_script` can list English and Hindi lines

Language metadata (`reply_language`, `allowed_languages`) is seeded at connect so Jinja prompts have defaults before the first user utterance. See [realtime-agents.md](../reference/realtime-agents.md#connect-time-initial-response).

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
| `GET /api/status` | Config + server health + `language_validation` issues |
| `GET /api/health` | Preflight (503 if media down) |
| `POST /v1/realtime/sessions` | Create session |
| `WS /v1/realtime/ws/{id}` | Full-duplex voice |

See also: [server.md](../reference/server.md), [model-servers.md](model-servers.md), [llm-litellm.md](llm-litellm.md).
