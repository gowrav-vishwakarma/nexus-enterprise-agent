# Instructions for AI assistants and contributors

When you change Nexus code, update the matching documentation in the same change.

## Documentation style

Follow [docs/style-guide.md](docs/style-guide.md). Write for beginners. Define terms on first use.

## What to update when code changes

| If you change… | Update these docs |
|----------------|-------------------|
| `nexus/orchestration/schema.py` or `nexus/orchestration/resolver.py` | `docs/reference/manifest-schema.md`, `docs/assets/complete-manifest.annotated.yaml` |
| `nexus/config/*.py` (fields, defaults, descriptions) | Matching file under `docs/reference/` |
| `OrchestrationRuntime` or `AgentRunner` signatures | `docs/reference/agent-runner.md`, `docs/assets/complete-run.annotated.py`, `docs/assets/complete-agent.annotated.py` |
| `.env.example` | `docs/reference/environment.md` |
| `examples/orchestration/*` | `docs/getting-started.md`, `docs/examples.md` |
| `examples/nexus_saas_api.py` | `docs/guides/saas-example.md` |
| `nexus/server/*` or `nexus/orchestration/schema.py` `servers:` | `docs/reference/server.md`, `docs/guides/model-servers.md`, `examples/servers.yaml` |

## README policy

Keep [README.md](README.md) short (~1000 lines). It is a quick start only. Move depth to `docs/`.

## Do not edit

- `NEXUS_AGENT_PRD.md` — design spec; link to it, do not rewrite unless asked.
