# SaaS API example

**Who this is for:** Developers building a multi-tenant chat API with plan tiers and per-tenant storage.

## Key terms

- **Tenant** — One customer organization (identified by `X-Tenant-ID` header).
- **Plan tier** — Subscription level (Free, Starter, Pro, Enterprise) that gates features.
- **BYOK** — Bring your own key; tenant supplies their LLM API key.

## What the example shows

[examples/nexus_saas_api.py](../../examples/nexus_saas_api.py) is a FastAPI app that:

1. Resolves tenant from `X-Tenant-ID` header
2. Builds `AgentConfig` from plan (tools, memory, RCS, skills)
3. Resolves `storage_config` per tenant on the runner
4. Runs chat and returns JSON or Server-Sent Events (SSE)

## Run it

```bash
uv sync --extra fastapi --extra sqlite --extra litellm
cp .env.example .env
uv run uvicorn examples.nexus_saas_api:app --host 0.0.0.0 --port 8000
```

## Mock tenants

| Tenant | Storage | Notes |
|--------|---------|-------|
| `free_tenant_1` | memory | 3 turns, no Postgres |
| `pro_tenant_1` | PostgreSQL | RCS, multi-agent, skills |

## Endpoints

**Single agent chat:**

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: free_tenant_1" \
  -d '{"message": "Hello"}'
```

**Multi-agent (Pro/Enterprise only):**

```bash
curl -X POST http://localhost:8000/v1/multi-agent/run \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: pro_tenant_1" \
  -d '{"message": "Research and analyze churn"}'
```

**Load team chat history:**

```http
GET /v1/sessions/{root_id}/group?pattern=pipeline&member_order=researcher,analyst
X-Tenant-ID: pro_tenant_1
X-User-ID: demo-user
```

## Headers

| Header | What it does |
|--------|--------------|
| `X-Tenant-ID` | Which customer (required) |
| `X-User-ID` | Which user (optional; needed for cross-chat memory) |

## Config factory priority (LLM)

1. `NEXUS_LLM_BASE_URL` set → all tenants use custom endpoint
2. Tenant BYOK key in mock tenant data
3. Platform keys from `PLATFORM_OPENAI_KEY` / `PLATFORM_ANTHROPIC_KEY`

## Streaming

Send `"stream": true` in the JSON body. Response is SSE from `/v1/chat`.

See [streaming reference](../reference/streaming.md).

## Architecture fit

| Concern | Where in example |
|---------|------------------|
| Agent behavior | `NexusTenantConfigFactory` → `AgentConfig` |
| Who is calling | `RunContext` from headers |
| Storage | `TenantPersistenceResolver` → `storage_config` on runner |
| Shared tools | `SHARED_TOOL_REGISTRY` + per-agent `tool_plugins` |

## Next steps

- [Architecture](../architecture.md)
- [Persistence resolver](persistence-resolver.md)
- [Environment variables](../reference/environment.md)
