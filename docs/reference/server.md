# Server configuration reference

## `ModelServerSpec`

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `kind` | Yes | — | Server type: `stt`, `tts`, `vad`, `lid` |
| `engine` | Yes | — | Engine plugin id (`mock`, `conformer`, `parler`, `silero`, `faster_whisper`) |
| `host` | No | `127.0.0.1` | Bind / connect host |
| `port` | Yes | — | gRPC port (1–65535) |
| `device` | No | — | GPU/CPU device string passed to engine |
| `replicas` | No | `1` | Number of TTS engine instances |
| `extra` | No | `{}` | Engine kwargs (`model_id`, `decoding`, `threshold`, …) |

## gRPC services

Defined in `nexus/server/proto/media.proto`:

- **SttService** — `StreamTranscribe` (bidi), `Transcribe` (unary)
- **TtsService** — `StreamSynthesize` (bidi), `Synthesize` (unary)
- **VadService** — `StreamVad` (bidi)
- **LidService** — `DetectLanguage` (unary)
- **HealthService** — `Check`, `Meta`

## Registry API

```python
from nexus.server.config import ModelServerSpec, ServersConfig
from nexus.server.registry import ServerRegistry

registry = ServerRegistry(ServersConfig(servers={
    "stt_main": ModelServerSpec(kind="stt", engine="mock", port=50051),
}))
target = registry.target_for("stt_main")  # "127.0.0.1:50051"
await registry.require_healthy(["stt_main"])
```

## Adapter providers

In agent manifest `stt` / `tts` / `vad` blocks, set:

- `provider: nexus_server` (aliases: `grpc`, `nexus`)
- `server_ref: <name>` — resolved via manifest `servers:` block
- `base_url: host:port` — direct endpoint override

## Optional dependencies

| Extra | Installs |
|-------|----------|
| `grpc` | grpcio, protobuf — agent client |
| `server` | torch, transformers, faster-whisper — GPU servers |
