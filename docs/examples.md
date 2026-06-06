# Examples index

**Who this is for:** Developers looking for runnable code beyond the getting-started guides.

## Key terms

- **Example** — A script or config in the `examples/` folder you can run or copy.
- **Fixture** — Test data under `tests/fixtures/` used by pytest.

## Orchestration (YAML)

| Path | What you will learn |
|------|---------------------|
| [examples/orchestration/research_team.yaml](../examples/orchestration/research_team.yaml) | Supervisor + nested pipeline team |
| [examples/orchestration/research_team_prompts.py](../examples/orchestration/research_team_prompts.py) | PROMPTS dict, Jinja templates |
| [examples/orchestration/run_team.py](../examples/orchestration/run_team.py) | CLI to load manifest and run |

```bash
uv run python examples/orchestration/run_team.py "Your question here"
```

Annotated references (not runnable as-is):

- [assets/complete-manifest.annotated.yaml](assets/complete-manifest.annotated.yaml)
- [assets/research_team_prompts.annotated.py](assets/research_team_prompts.annotated.py)
- [assets/complete-run.annotated.py](assets/complete-run.annotated.py)

## SaaS API

| Path | What you will learn |
|------|---------------------|
| [examples/nexus_saas_api.py](../examples/nexus_saas_api.py) | FastAPI multi-tenant app, plan gating, streaming, `/v1/chat/vision` |

Guide: [guides/saas-example.md](guides/saas-example.md).

## Voice, realtime, and channels

| Path | What you will learn |
|------|---------------------|
| [examples/orchestration/ivr_support.yaml](../examples/orchestration/ivr_support.yaml) | Half-duplex IVR voice agent (cascaded) |
| [examples/orchestration/voice_assistant.yaml](../examples/orchestration/voice_assistant.yaml) | Full-duplex (barge-in) browser voice agent |
| [examples/orchestration/voice_team_support.yaml](../examples/orchestration/voice_team_support.yaml) | Voice team: responder + context agent |
| [examples/realtime_ivr_server.py](../examples/realtime_ivr_server.py) | Run the IVR pipeline locally (no keys needed) |
| [examples/realtime_browser_voice.py](../examples/realtime_browser_voice.py) | Browser mic demo over WebSocket |
| [examples/orchestration/voice_local.yaml](../examples/orchestration/voice_local.yaml) | English cascaded voice (Whisper + Kokoro + Ollama) |
| [examples/orchestration/voice_local_indic.yaml](../examples/orchestration/voice_local_indic.yaml) | Hindi cascaded voice (Indic-Conformer + Indic Parler + Ollama) |
| [examples/orchestration/VOICE_PROFILES.md](../examples/orchestration/VOICE_PROFILES.md) | Profile ↔ manifest map (24 GB VRAM, one at a time) |
| [examples/realtime_local_voice.py](../examples/realtime_local_voice.py) | Run the all-local cascaded turn (`--check` probes servers) |
| [examples/realtime_local_voice_ui.py](../examples/realtime_local_voice_ui.py) | Push-to-talk browser UI on local models (STT→LLM→TTS) |
| [examples/orchestration/voice_s2s_local.yaml](../examples/orchestration/voice_s2s_local.yaml) | Speech-to-speech via Moshi or Human-1 (`NEXUS_S2S_PROVIDER`) |
| [examples/realtime_s2s_ui.py](../examples/realtime_s2s_ui.py) | Full-duplex speech-to-speech browser UI (Moshi) |
| [examples/realtime_saas_api.py](../examples/realtime_saas_api.py) | Realtime SaaS API: sessions, voice WS, Twilio/SIP, channels, plan gating |

Reference: [reference/realtime-agents.md](reference/realtime-agents.md).

```bash
uv run python examples/realtime_ivr_server.py "I want to pay my bill"
```

## Python API (annotated)

| Path | What you will learn |
|------|---------------------|
| [assets/complete-agent.annotated.py](assets/complete-agent.annotated.py) | Every AgentConfig and AgentRunner parameter |

Walkthrough: [getting-started-python.md](getting-started-python.md).

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
- [Documentation index](index.md)
