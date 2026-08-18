# Instructions for AI assistants and contributors

When you change Nexus code, update the matching documentation in the same change. Even if you ever finds this Agents.md file is out of oder. update this as well with new patterns, file paths etc.

Before making any new feature or code, make sure that we do not have anything like that first. no DRY un less that gives more profit.

Always keeps things siple. keep things modular and easy to understand but no unnecessary complexity and DO Avoid Over Engineering. 

## Documentation style

Follow [docs/style-guide.md](docs/style-guide.md). Write for beginners. Define terms on first use.
When checking behaviour, read the docs first, then the code; if they disagree, update the docs in the same change.

## What to update when code changes

| If you change… | Update these docs |
|----------------|-------------------|
| `nexus/orchestration/schema.py` or `nexus/orchestration/resolver.py` | `docs/reference/manifest-schema.md`, `docs/assets/complete-manifest.annotated.yaml` |
| `nexus/config/*.py` (fields, defaults, descriptions) | Matching file under `docs/reference/` |
| `nexus/scope.py` | `docs/reference/scope.md` |
| `nexus/guardrails/*` | `docs/reference/guardrails.md` |
| `nexus/mcp/*` | `docs/reference/mcp.md` |
| `nexus/rag/*` | `docs/reference/rag.md` |
| `nexus/memory/*` | `docs/reference/memory.md` |
| `nexus/skills/models.py` or `nexus/skills/plugin.py` | `docs/reference/skills.md` |
| `nexus/multiagent/orchestrator.py` | `docs/reference/multi-agent.md` |
| `nexus/serve/*`, `nexus/cli/*` | `docs/reference/serve.md` |
| `nexus/serve/replay.py` | `docs/reference/streaming.md` (Reattaching to a dropped stream), `docs/reference/serve.md` |
| `nexus/events/emitter.py` or `nexus/guardrails/redaction.py` / `audit.py` | `docs/reference/events.md`, `docs/reference/guardrails.md` |
| `templates/*` | `docs/examples.md` (Starter templates) and that template's `README.md` |
| `nexus/eval/*` | `docs/reference/eval.md` |
| `nexus/jobs/*`, `nexus/artifacts/*`, `nexus/cache/*`, `nexus/runner/checkpoint.py` | `docs/reference/jobs.md` |
| `nexus/tools/decorators.py` or `nexus/tools/registry.py` | `docs/reference/tools.md` |
| Any new `docs/reference/*.md` page | Add it to the Quick links table in `docs/index.md` |
| `OrchestrationRuntime` or `AgentRunner` signatures | `docs/reference/agent-runner.md`, `docs/assets/complete-run.annotated.py`, `docs/assets/complete-agent.annotated.py` |
| `nexus/llm/content_tool_calls.py` or assistant history sanitization in `agent_runner` / `context/builder` | `docs/reference/agent-runner.md` (Content-side tool-call recovery) |
| `.env.example` | `docs/reference/environment.md` |
| `examples/orchestration/*` | `docs/getting-started.md`, `docs/examples.md` |
| `examples/nexus_saas_api.py` | `docs/guides/saas-example.md` |
| `nexus/server/*` or `nexus/orchestration/schema.py` `servers:` | `docs/reference/server.md`, `docs/guides/model-servers.md`, `examples/servers.yaml` |

## how to run python code

the project is made with uv, so any python code must be run with uv to pick all dependencies.

```bash
uv sync --extra sqlite --extra file
uv run pytest
uv run pytest -m live_llm   # real LLM calls; needs NEXUS_LLM_* in .env
```

Test tools (pytest, ruff, aiosqlite, …) live in `[dependency-groups] dev`, which `uv sync` installs by default. Do not `uv pip install` them into a local venv — that skips the lockfile and other machines will miss the packages. Use `uv add --dev <pkg>` if you need a new test dependency.

## README policy

Keep [README.md](README.md) short (~1000 lines). It is a quick start only. Move depth to `docs/`.

## Do not edit

- `NEXUS_AGENT_PRD.md` — design spec; link to it, do not rewrite unless asked.
