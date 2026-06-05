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

## Realtime / voice (app-level, optional)

Used by the realtime examples and manifests. STT/TTS default to `mock` (no keys)
so demos run offline. See [realtime-agents.md](realtime-agents.md).

| Variable | What it does |
|----------|--------------|
| `NEXUS_STT_PROVIDER` | STT provider (`mock`, `openai`, `deepgram`, `local`) |
| `NEXUS_STT_MODEL` | STT model (e.g. `nova-3`) |
| `NEXUS_TTS_PROVIDER` | TTS provider (`mock`, `openai`, `local`) |
| `NEXUS_TTS_MODEL` / `NEXUS_TTS_VOICE` | TTS model / voice |
| `DEEPGRAM_API_KEY` | Deepgram STT key |
| `OPENAI_VISION_MODEL` | Vision model for image attachments (default `gpt-4o`) |

### Self-hosted / offline-first (BYOM)

Point the OpenAI-compatible adapters at your own local model servers (no paid API).
Used by `voice_local.yaml`, `voice_s2s_local.yaml`, and the `realtime_local_voice*`
/ `realtime_s2s_ui` examples.

| Variable | What it does |
|----------|--------------|
| `NEXUS_STT_BASE_URL` | Local STT endpoint (e.g. `http://localhost:8001/v1`) |
| `NEXUS_TTS_BASE_URL` | Local TTS endpoint (e.g. `http://localhost:8002/v1`) |
| `NEXUS_LLM_BASE_URL` / `NEXUS_LLM_MODEL` | Local LLM (e.g. Ollama `http://localhost:11434/v1`, `gpt-oss:latest`) |
| `NEXUS_S2S_PROVIDER` / `NEXUS_S2S_BASE_URL` | Speech-to-speech (e.g. `moshi`, `ws://localhost:8998`) |

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
