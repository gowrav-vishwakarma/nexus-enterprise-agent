# Realtime, voice, vision, and channels

**Who this is for:** Developers adding voice (phone/browser), images, or
messaging channels (Telegram/WhatsApp) to Nexus agents.

Everything here is built **on top of the unchanged text `AgentRunner`**. A voice
agent is "just an agent config plus a modality", so your personas, tools, memory,
and RCS all work the same. These features live in two optional packages:

- `nexus.realtime` — voice (cascaded + speech-to-speech), vision, IVR, voice teams.
- `nexus.channels` — messaging channels (Telegram, WhatsApp, ...).

Install the optional extras:

```bash
pip install "nexus-enterprise-agent[realtime]"      # websockets + httpx
# providers as needed, e.g. deepgram (STT), openai (TTS/Realtime/Whisper)
```

## Key terms

- **Modality** — How an agent handles media: `text`, `vision_text`, `voice_cascaded`, `voice_s2s`.
- **Cascaded voice** — A pipeline of separate stages: VAD → STT → LLM → TTS.
- **Speech-to-speech (S2S)** — One realtime model that takes audio and returns audio.
- **VAD** — Voice Activity Detection: decides when the caller started/stopped talking.
- **STT / TTS** — Speech-to-text / text-to-speech.
- **Duplex** — `half` = strict turn-taking (IVR); `full` = the user can interrupt (barge-in).
- **Channel** — An I/O edge (browser, phone, Telegram, WhatsApp) normalized to agent input.

## Multimodal input

`UserInput` carries text plus optional images and audio. It is the input type for
vision and channels.

```python
from nexus.realtime import UserInput

UserInput.from_text("hello")
UserInput.from_image_url("https://example.com/cat.png", text="what is this?")
UserInput.from_image_bytes(png_bytes, text="describe", mime_type="image/png")
```

### Vision (images)

`VisionAgentRunner` wraps `AgentRunner` and injects images into the user message
as an OpenAI-style multimodal content array. Text-only inputs behave exactly like
the normal runner.

```python
from nexus.realtime import VisionAgentRunner, UserInput

runner = VisionAgentRunner(config=agent_config, tool_registry=registry)
result = await runner.run(UserInput.from_image_bytes(img, text="What's in this photo?"))
```

The SaaS example exposes this at `POST /v1/chat/vision` (multipart upload).

## Cascaded voice (VAD → STT → LLM → TTS)

`CascadedVoicePipeline` is modular: each stage is swappable. The agent's streamed
text reply is synthesized sentence-by-sentence, so audio starts before the full
reply is ready.

```python
from nexus.realtime import CascadedVoicePipeline, RealtimeAgentConfig

pipeline = CascadedVoicePipeline(rt_config, storage_config=session_manager)

# Already-transcribed text:
async for ev in pipeline.process_text("book a flight", session_id="s1"):
    ...
# One audio blob (half-duplex / voice note):
async for ev in pipeline.process_utterance(wav_bytes, session_id="s1"):
    ...
# Continuous audio stream (segmented by VAD; full-duplex supports barge-in):
async for ev in pipeline.process_audio_stream(audio_frames, session_id="s1"):
    ...
```

Each step yields a `RealtimeStreamEvent` (`transcript_final`, `content`,
`audio_out`, `tool_call`, `barge_in`, `final_response`, ...).

### Providers

| Stage | Providers | Notes |
|-------|-----------|-------|
| STT | `mock`, `openai` (Whisper), `deepgram` | Deepgram supports streaming partials |
| TTS | `mock`, `openai` | Streams per sentence |
| VAD | `energy` (built-in), `silero` | `energy` needs no extra deps |

`mock` providers run with no keys (handy for tests/demos): mock STT decodes bytes
as UTF-8 text; mock TTS returns `b"AUDIO:" + text`.

## Speech-to-speech (S2S)

`SpeechToSpeechPipeline` drives a single realtime model (e.g. OpenAI Realtime).
It still uses your agent's persona (as instructions) and **bridges your tools** to
the model's function calling, so voice agents keep the same tools as text agents.

```python
from nexus.realtime import SpeechToSpeechPipeline
pipeline = SpeechToSpeechPipeline(rt_config, tool_registry=registry, run_context=ctx)
async for ev in pipeline.process_audio_stream(audio_frames):
    ...
```

Tool names are sanitized for the realtime API (`plugin.tool` → `plugin-tool`) and
mapped back automatically when executing.

## Half-duplex IVR

For phone menus, set `duplex: half` and give the agent the `ivr_menu` plugin. Its
tools let the LLM drive the call: `play_prompt`, `collect_dtmf`, `transfer_call`,
`hang_up`. DTMF the caller presses is read from `RunContext.metadata['dtmf_buffer']`,
which the transport (WebSocket/SIP) populates.

See [examples/orchestration/ivr_support.yaml](../../examples/orchestration/ivr_support.yaml).

## Full-duplex (barge-in)

With `duplex: full`, `process_audio_stream` listens while it speaks. A new
`SPEECH_START` while the agent is talking emits a `barge_in` event and cancels the
in-flight response. Streaming STT (e.g. Deepgram) enables earlier ("preemptive")
generation.

## Voice teams (multi-agent voice)

`VoiceTeam` implements the "group of agents" idea: a **responder** speaks with the
user, an optional **context_agent** silently looks up relevant info per turn and
injects it into the responder, and an optional **listener** provides a dedicated
transcription path.

```yaml
groups:
  support_team:
    pattern: voice_team
    context_injection_var: live_context
    members:
      - {name: responder, role: responder}
      - {name: context_agent, role: context_agent}
```

```python
team = RealtimeRuntime.from_manifest(manifest, run_context=ctx).build_voice_team("support_team")
async for ev in team.process_text("where is my order"):
    ...
```

See [examples/orchestration/voice_team_support.yaml](../../examples/orchestration/voice_team_support.yaml).

## Transports

A transport moves audio/events between the client and the pipeline.

| Transport | Use case | Extra |
|-----------|----------|-------|
| `InMemoryTransport` | tests, local simulation | — |
| `WebSocketTransport` | browser / generic WS (PCM16) | — |
| `TwilioMediaStreamTransport` | phone via Twilio/SIP (mu-law 8 kHz) | — |
| `LiveKitTransport` | WebRTC | `livekit` |

`RealtimeSession` binds a pipeline to a transport and pumps audio both ways:

```python
from nexus.realtime import RealtimeSession
session = RealtimeSession(pipeline, transport, session_id="call-1", event_emitter=emitter)
await session.run_audio()
```

When given an `event_emitter`, the session emits OpenTelemetry-friendly events:
`realtime.session_started`, `realtime.transcribed`, `realtime.barge_in`,
`realtime.response_completed`, `realtime.session_ended`.

## Messaging channels

A **channel** normalizes any provider into `UserInput` + `RunContext`, runs your
agent, and renders the reply back. Voice notes are transcribed via STT; images are
routed to a `VisionAgentRunner`.

```python
from nexus.channels import ChannelRouter, TelegramAdapter, StaticIdentityResolver

adapter = TelegramAdapter(token)
router = ChannelRouter(
    adapter,
    executor_factory=lambda ctx: AgentRunner(config, registry, sm, ctx),
    identity_resolver=StaticIdentityResolver(tenant_id="acme"),
    stt=stt,                              # transcribe voice notes
    vision_executor_factory=lambda ctx: VisionAgentRunner(config, registry, sm, ctx),
)
output = await router.handle(update_payload)   # call from your webhook
```

Built-in adapters: `TelegramAdapter`, `WhatsAppAdapter` (Meta Cloud API). The
SaaS example exposes a generic `POST /v1/channels/{name}/webhook`.

## SaaS endpoints

The realtime SaaS example (`examples/realtime_saas_api.py`) shows production wiring:

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/realtime/sessions` | Bootstrap a voice session (returns WS URL + audio format) |
| `WS /v1/realtime/ws/{sid}` | Browser voice (PCM16 frames in, events + audio out) |
| `WS /v1/realtime/twilio/{sid}` | Phone via Twilio Media Streams (mu-law) |
| `POST /v1/realtime/sip/inbound` | SIP inbound webhook (returns media WS URL) |
| `POST /v1/channels/{name}/webhook` | Telegram/WhatsApp inbound |
| `GET /v1/channels/whatsapp/webhook` | WhatsApp verification handshake |

Plan-tier gating (`check_realtime_access`) restricts which agents/modalities each
plan can use and caps concurrent sessions.

```bash
uv run --extra fastapi --extra realtime --extra openai \
    uvicorn examples.realtime_saas_api:app --reload
```

## Next steps

- [Manifest schema](manifest-schema.md) — realtime agent + channel fields
- [Examples index](../examples.md)
- [SaaS example](../guides/saas-example.md)
