# Serving (`nexus[serve]`)

Mountable FastAPI routers so products don't rewrite the same chat API.

```python
from nexus.serve import create_agent_router, AgentRouterConfig

router = create_agent_router(runner_factory, context_factory, config=AgentRouterConfig(prefix="/v1"))
app.include_router(router)
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/chat` | Blocking chat |
| POST | `/v1/chat/stream` | SSE stream |
| GET | `/v1/sessions/{id}/stream` | Reattach to a dropped stream |
| POST | `/v1/sessions/{id}/resume` | Resume paused run |
| GET | `/v1/sessions/{id}` | Session history |

`context_factory` receives the FastAPI `Request`, so read tenant and user from
headers or a token there and return a `RunContext`. Everything downstream —
sessions, memory, artifacts, and the replay buffer — is partitioned by it.

## Reconnecting clients

Stream frames carry an `id:` line with the event's sequence number.
`GET /v1/sessions/{id}/stream` replays the events after the client's
`Last-Event-ID` and then follows the run to completion, so a dropped connection
does not cost a second agent run. Retention and multi-worker caveats are covered in
[streaming.md](streaming.md#reattaching-to-a-dropped-stream).

## CLI

```bash
nexus serve --port 8000
nexus manifest validate team.yaml
nexus doctor
nexus eval dataset.json
```

See [Dockerfile](../../Dockerfile) for container deployment.
