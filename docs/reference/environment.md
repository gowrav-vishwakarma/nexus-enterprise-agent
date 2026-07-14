# Environment variables

**Who this is for:** Developers configuring paths, databases, and LLM endpoints.

## Key terms

- **Framework vars** — Read inside Nexus (data paths, skills root).
- **App vars** — Your application reads these; Nexus config models do not auto-load LLM keys.

Nexus builds `LLMProviderConfig` explicitly in code or via `${ENV:...}` in YAML manifests.

## Framework path defaults

| Variable | Default | What it does |
|----------|---------|--------------|
| `NEXUS_DATA_ROOT` | `./tenants` | Root folder for tenant/user session and memory files |
| `NEXUS_SKILLS_ROOT` | `./skills` | Root folder for agentskills.io `SKILL.md` folders |

Layout under `NEXUS_DATA_ROOT`:

```text
{NEXUS_DATA_ROOT}/{tenant_id}/users/{user_id}/
  sessions.db
  memory.db
  {session_id}/session.json
```

## PostgreSQL (production)

| Variable | What it does |
|----------|--------------|
| `NEXUS_PG_DSN` | Database connection string |
| `NEXUS_PG_SCHEMA` | Schema name |
| `NEXUS_PG_SCHEMA_MODE` | `managed`, `qualified`, or `existing` |
| `NEXUS_PG_AUTO_MIGRATE` | `true` to run DDL (default false in production) |

## Redis

| Variable | What it does |
|----------|--------------|
| `NEXUS_REDIS_URL` | Redis connection URL |
| `NEXUS_REDIS_TTL_SECONDS` | Key time-to-live |

## SaaS example (app-level)

| Variable | What it does |
|----------|--------------|
| `PLATFORM_OPENAI_KEY` | Platform OpenAI key when tenant has no BYOK |
| `PLATFORM_ANTHROPIC_KEY` | Platform Anthropic key |
| `NEXUS_LLM_PROVIDER` | Adapter when using custom endpoint |
| `NEXUS_LLM_BASE_URL` | Custom LLM API base URL |
| `NEXUS_LLM_API_KEY` | Key for custom endpoint |
| `NEXUS_LLM_MODEL` | Model string for custom endpoint |

When `NEXUS_LLM_BASE_URL` is set, the SaaS example routes all tenants through that endpoint.

## Realtime / voice — Voice Lab (gRPC)

Used by Voice Lab and `voice_grpc.yaml`. Media servers run as gRPC processes;
the agent connects via `provider: nexus_server` and `server_ref`.

| Variable | What it does |
|----------|--------------|
| `LITELLM_BASE_URL` | LLM endpoint (LiteLLM proxy, Ollama, vLLM) |
| `LITELLM_API_KEY` | API key for LLM endpoint |
| `VOICE_LLM_MODEL` | Voice agent model (e.g. `ollama/qwen3:4b`) |
| `STT_ENGINE` | STT server engine (`conformer`, `mock`) |
| `TTS_ENGINE` | TTS server engine (`parler`, `mock`) |
| `VAD_ENGINE` | VAD server engine (`silero`, `mock`) |
| `STT_DEVICE` / `TTS_DEVICE` | GPU/CPU for media servers |
| `TTS_SAMPLE_RATE` | TTS output rate (Parler = 44100, mock/kokoro = 24000) |
| `STT_LANGUAGE` | STT language code (e.g. `hi`) |
| `VAD_PROVIDER` | Agent-side VAD (`energy` or `nexus_server`) |
| `NEXUS_VOICE_MANIFEST` | Agent YAML path |
| `VOICE_LAB_PORT` | Voice Lab UI port (default `8787`) |
| `NEXUS_SERVERS_CONFIG` | Media servers YAML (default `examples/servers.yaml`) |

gRPC ports (defaults): STT `50051`, TTS `50052`, VAD `50053`, LID `50054`.

> **Parler TTS:** install separately (`uv pip install parler-tts`) then repin
> protobuf (`uv pip install "protobuf>=5.26"`). `run_voice_lab.sh` does this
> when `TTS_ENGINE=parler`. Model weights download on first use.

See [voice-lab.md](../guides/voice-lab.md) and [model-servers.md](../guides/model-servers.md).

## Realtime / voice — cloud providers

For manifests that use cloud STT/TTS directly (no gRPC servers), e.g. `ivr_support.yaml`:

| Variable | What it does |
|----------|--------------|
| `NEXUS_STT_PROVIDER` | STT provider (`mock`, `openai`, `deepgram`) |
| `NEXUS_STT_MODEL` | STT model (e.g. `nova-3`) |
| `NEXUS_TTS_PROVIDER` | TTS provider (`mock`, `openai`) |
| `NEXUS_TTS_MODEL` / `NEXUS_TTS_VOICE` | TTS model / voice |
| `DEEPGRAM_API_KEY` | Deepgram STT key |
| `OPENAI_VISION_MODEL` | Vision model for image attachments (default `gpt-4o`) |

## Speech-to-speech (S2S)

Used by `voice_s2s_local.yaml` and `realtime_s2s_ui.py`:

| Variable | What it does |
|----------|--------------|
| `NEXUS_S2S_PROVIDER` / `NEXUS_S2S_BASE_URL` | S2S provider (`moshi`, `human-1`, `ws://localhost:8998`) |

## Messaging channels (app-level, optional)

| Variable | What it does |
|----------|--------------|
| `TELEGRAM_BOT_TOKEN` | Enables the Telegram channel adapter |
| `WHATSAPP_TOKEN` | WhatsApp Cloud API access token |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp sender phone number id |
| `WHATSAPP_VERIFY_TOKEN` | Webhook verification token (default `nexus-verify`) |

## Integration tests

| Variable | What it does |
|----------|--------------|
| `NEXUS_TEST_PG_DSN` | Test PostgreSQL DSN |
| `NEXUS_TEST_REDIS_URL` | Test Redis URL |

See `docker-compose.test.yml` in the repo root.

## YAML env interpolation

In orchestration manifests only:

```yaml
api_key: ${ENV:OPENAI_API_KEY}
model: ${ENV:OPENAI_MODEL|gpt-4o}
```

## Next steps

- [Storage](storage.md)
- [SaaS guide](../guides/saas-example.md)
- [.env.example](../../.env.example)
