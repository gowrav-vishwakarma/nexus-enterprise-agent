# Voice agent starter

Voice needs a media path (microphone, telephony, or WebRTC) alongside the agent, so
the runnable starters live with the other realtime examples rather than being
duplicated here.

| Start from | When |
|------------|------|
| [examples/voice_lab.py](../../examples/voice_lab.py) | Browser microphone, quickest to hear something |
| [examples/realtime_ivr_server.py](../../examples/realtime_ivr_server.py) | Telephony / IVR call flows |
| [examples/realtime_s2s_ui.py](../../examples/realtime_s2s_ui.py) | Speech-to-speech with a UI |
| [examples/realtime_saas_api.py](../../examples/realtime_saas_api.py) | Multi-tenant voice behind an API |

```bash
uv run python examples/voice_lab.py
```

Guides: [voice-lab.md](../../docs/guides/voice-lab.md) and
[model-servers.md](../../docs/guides/model-servers.md) for `nexus[grpc]` media
servers or cloud STT/TTS.
