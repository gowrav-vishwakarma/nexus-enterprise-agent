# Nexus

**Enterprise-ready agent framework.** Describe agents in config. Wire who is calling and where data lives at run time. Call `run()`.

No global LLM settings. No shared agent singleton. Built for multi-tenant SaaS apps.

---

## Install

Published on PyPI as [`nexus-enterprise-agent`](https://pypi.org/project/nexus-enterprise-agent/). Import in Python as `nexus`.

**pip**

```bash
pip install nexus-enterprise-agent
```

**uv**

```bash
uv add nexus-enterprise-agent
```

**Optional extras** — combine with commas inside brackets:

| Extra | Adds |
|-------|------|
| `sqlite`, `postgres`, `redis`, `file` | Storage adapters |
| `openai`, `anthropic`, `gemini`, `litellm`, `groq`, `ollama` | LLM provider clients |
| `fastapi` | FastAPI + SSE helpers |
| `otel` | OpenTelemetry exporters |
| `all` | Everything above |

```bash
pip install "nexus-enterprise-agent[sqlite,litellm,fastapi]"
```

**From GitHub** (latest main, not a PyPI release):

```bash
pip install "git+https://github.com/gowrav-vishwakarma/nexus-enterprise-agent.git"
```

**Contributors** — clone and sync the repo:

```bash
git clone https://github.com/gowrav-vishwakarma/nexus-enterprise-agent.git
cd nexus-enterprise-agent
uv sync --extra dev --extra sqlite --extra file
```

For the SaaS API example, also add `--extra fastapi --extra litellm`.

Copy [.env.example](.env.example) to `.env` and set your LLM API key.

Run tests:

```bash
uv run pytest
```

---

## Run in 3 steps

| Step | File | Purpose |
|------|------|---------|
| 1 | `team.yaml` | What agents exist and how they connect |
| 2 | `team_prompts.py` | How they speak (prompt templates) |
| 3 | Short Python script | Who is calling (tenant, user, chat id) |

The repo includes a working team at [examples/orchestration/](examples/orchestration/).

```bash
uv run python examples/orchestration/run_team.py "Analyze Q4 revenue"
```

---

## Minimal example

```python
import asyncio
from nexus import OrchestrationManifest, OrchestrationRuntime, RunContext

async def main():
    manifest = OrchestrationManifest.load("examples/orchestration/research_team.yaml")
    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        run_context=RunContext(
            tenant_id="demo",
            user_id="user-1",
            session_id="chat-1",  # set before building runtime for teams
        ),
    )
    result = await runtime.run("Analyze Q4 revenue")
    print(result.final_response)

asyncio.run(main())
```

Every parameter (optional fields and defaults) is documented in [docs/assets/complete-manifest.annotated.yaml](docs/assets/complete-manifest.annotated.yaml) and [docs/assets/complete-run.annotated.py](docs/assets/complete-run.annotated.py).

---

## Learn more

Full documentation: **[docs/index.md](docs/index.md)**

| Topic | Doc |
|-------|-----|
| Architecture (what goes where) | [docs/architecture.md](docs/architecture.md) |
| YAML walkthrough | [docs/getting-started.md](docs/getting-started.md) |
| Python API walkthrough | [docs/getting-started-python.md](docs/getting-started-python.md) |
| All YAML fields + defaults | [docs/reference/manifest-schema.md](docs/reference/manifest-schema.md) |
| Memory (cross-session facts) | [docs/reference/memory.md](docs/reference/memory.md) |
| Context summary (long chats) | [docs/reference/context-summary.md](docs/reference/context-summary.md) |
| Multi-tenant SaaS example | [docs/guides/saas-example.md](docs/guides/saas-example.md) |
| Example index | [docs/examples.md](docs/examples.md) |
| Full design spec | [NEXUS_AGENT_PRD.md](NEXUS_AGENT_PRD.md) |

---

## Examples

- [examples/orchestration/](examples/orchestration/) — YAML multi-agent team
- [examples/nexus_saas_api.py](examples/nexus_saas_api.py) — FastAPI SaaS API with plan tiers

```bash
uv run uvicorn examples.nexus_saas_api:app --host 0.0.0.0 --port 8000
```
