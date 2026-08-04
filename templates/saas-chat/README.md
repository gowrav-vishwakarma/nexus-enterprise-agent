# SaaS chat API starter

A multi-tenant chat API: one FastAPI app, one agent, scoped per request.

```bash
export OPENAI_API_KEY=sk-...
uv run uvicorn templates.saas-chat.main:app --reload
```

```bash
curl -X POST localhost:8000/v1/chat \
  -H 'x-tenant-id: acme' -H 'x-user-id: u1' \
  -H 'content-type: application/json' -d '{"message": "hello"}'
```

## What [main.py](main.py) shows

- `context_factory` turns each request into a `RunContext`. Sessions, memory, and
  buffered streams are all partitioned by it, so swap the headers for your real auth
  and never default the tenant.
- `RedactingEventSink` keeps customer emails, phone numbers, and API tokens out of
  traces — see [events.md](../../docs/reference/events.md#keeping-customer-data-out-of-traces).
- `AuditSink` records which tools ran, keyed by scope.
- `StreamReplayBuffer` lets a browser that loses its connection rejoin a run instead
  of paying for a second one — see
  [streaming.md](../../docs/reference/streaming.md#reattaching-to-a-dropped-stream).

For a larger walkthrough with tools and manifests, see
[examples/nexus_saas_api.py](../../examples/nexus_saas_api.py) and
[docs/guides/saas-example.md](../../docs/guides/saas-example.md).
