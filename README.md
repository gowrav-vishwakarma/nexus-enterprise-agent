# Nexus

**Enterprise-ready agent framework.** Describe agents in config. Wire who is calling and where data lives at run time. Call `run()`.

No global LLM settings. No shared agent singleton. Built for multi-tenant SaaS apps.

> **Beta — under active development.** APIs and behaviour may change between releases. Nexus is published early so the community can try it, report issues, and contribute — not as a finished production guarantee. See [NEXUS_AGENT_PRD.md](NEXUS_AGENT_PRD.md) for the design spec and open a PR if you want to help build it.

## Why another agent framework?

LangGraph, CrewAI, AutoGen, OpenAI Agents SDK, Pydantic AI, and LangChain each solve parts of the problem — but production SaaS workloads expose recurring gaps:

| Framework | Gap for production SaaS |
|-----------|-------------------------|
| LangGraph | Graph-coupled state machines; awkward in stateless HTTP APIs |
| CrewAI | Opinionated roles; high token overhead on simple tasks |
| AutoGen / AG2 | GroupChat bloat; full history every turn; env-var config |
| OpenAI Agents SDK | Model-locked; no durable context management; no BYOM |
| Pydantic AI | Strong types, but context compression is still manual |
| LangChain | Token-efficient patterns, but heavy architecture and churn |

**Nexus** targets what those stacks under-serve: **long-horizon agents in multi-tenant apps**, where **context is the scarcest resource**.

- **SaaS-native** — zero global state; tenant, user, API keys, and storage passed per request
- **Context-first (RCS)** — the agent compresses old tool results inline via `_context_updates`; no extra LLM calls
- **Config-driven teams** — YAML manifests for multi-agent orchestration; Python only for wiring and tools
- **Provider-agnostic** — bring your own model; pluggable SQLite, Postgres, Redis, or file storage
- **Voice, vision & channels** — optional cascaded/speech-to-speech voice, image input, IVR, and Telegram/WhatsApp on the same agent core ([docs](docs/reference/realtime-agents.md))

Full landscape analysis and design rationale: [NEXUS_AGENT_PRD.md](NEXUS_AGENT_PRD.md).

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

## Two-agent SaaS sketch

**The examples below are the same support team expressed two ways** — pick YAML manifests or programmatic Python config. Both use a supervisor group (`lead` delegates to `specialist`), one dummy tool per agent, SQLite storage, and a per-request FastAPI endpoint scoped by tenant and user.

| | YAML way | Programmatic way |
|---|----------|------------------|
| Define agents & group | `team.yaml` | `AgentConfig` + `AgentGroupConfig` in Python |
| Load at startup | `OrchestrationManifest.load(...)` | `build_support_team()` factory |
| Run per request | `OrchestrationRuntime.from_manifest(...)` | `AgentOrchestrator(...)` |

**Shared — `myapp/tools.py`** (identical for both ways)

```python
from nexus.tools.decorators import tool, tool_plugin

@tool_plugin("lookup")
class LookupPlugin:
    @tool()
    def lookup_account(self, account_id: str) -> str:
        """Look up a customer account."""
        return f"Account {account_id}: active, plan=pro"

@tool_plugin("echo")
class EchoPlugin:
    @tool()
    def echo(self, message: str) -> str:
        """Echo a message for confirmation."""
        return f"Echo: {message}"
```

### Way 1 — Programmatic Python

**`myapp/team.py`** — same agents and group as `team.yaml`

```python
import os
from pydantic import SecretStr
from nexus import AgentConfig, AgentGroupConfig, AgentPersonaConfig, LLMProviderConfig

LLM = LLMProviderConfig(
    provider="openai",
    model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    api_key=SecretStr(os.environ["OPENAI_API_KEY"]),
)

def build_support_team() -> AgentGroupConfig:
    lead = AgentConfig(
        name="lead",
        llm=LLM,
        tool_plugins=["lookup"],
        persona=AgentPersonaConfig(
            role="Support lead",
            goal="Route tickets and look up accounts",
        ),
    )
    specialist = AgentConfig(
        name="specialist",
        llm=LLM,
        tool_plugins=["echo"],
        persona=AgentPersonaConfig(
            role="Specialist",
            goal="Confirm technical details with the echo tool",
        ),
    )
    return AgentGroupConfig(
        name="support_team",
        pattern="supervisor",
        members=[lead, specialist],   # lead supervises; specialist is delegated to
    )
```

**`myapp/app_programmatic.py`**

```python
from uuid import uuid4
from fastapi import FastAPI, Header
from pydantic import BaseModel
from nexus import AgentOrchestrator, RunContext, SessionStorageConfig
from nexus.session.manager import SessionManager
from nexus.tools.registry import ToolRegistry
from myapp.team import build_support_team
from myapp.tools import LookupPlugin, EchoPlugin

GROUP = build_support_team()
REGISTRY = ToolRegistry()
REGISTRY.register_plugin(LookupPlugin())
REGISTRY.register_plugin(EchoPlugin())
STORAGE = SessionManager.from_config(SessionStorageConfig(
    adapter="sqlite",
    adapter_config={"data_root": "./data"},
))

app = FastAPI()

class ChatIn(BaseModel):
    message: str
    session_id: str | None = None

@app.post("/v1/chat")
async def chat(
    body: ChatIn,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    user_id: str = Header("demo-user", alias="X-User-ID"),
):
    session_id = body.session_id or str(uuid4())
    orchestrator = AgentOrchestrator(
        config=GROUP,
        tool_registry=REGISTRY,
        storage_config=STORAGE,
        run_context=RunContext(tenant_id=tenant_id, user_id=user_id, session_id=session_id),
    )
    result = await orchestrator.run(body.message, session_id=session_id)
    return {"session_id": session_id, "response": result.final_response}
```

### Way 2 — YAML manifest

**`team.yaml`**

```yaml
version: "1"
root: support_team

defaults:
  llm:
    provider: openai
    model: ${ENV:OPENAI_MODEL|gpt-4o-mini}
    api_key: ${ENV:OPENAI_API_KEY}

storage:
  adapter: sqlite
  adapter_config:
    data_root: ./data

plugins:
  lookup: myapp.tools.LookupPlugin
  echo: myapp.tools.EchoPlugin

agents:
  lead:
    tool_plugins: [lookup]
    persona:
      role: Support lead
      goal: Route tickets and look up accounts

  specialist:
    tool_plugins: [echo]
    persona:
      role: Specialist
      goal: Confirm technical details with the echo tool

groups:
  support_team:
    pattern: supervisor
    members: [lead, specialist]   # lead supervises; specialist is delegated to
```

**`myapp/app_yaml.py`**

```python
from uuid import uuid4
from fastapi import FastAPI, Header
from pydantic import BaseModel
from nexus import OrchestrationManifest, OrchestrationRuntime, RunContext

MANIFEST = OrchestrationManifest.load("team.yaml")
app = FastAPI()

class ChatIn(BaseModel):
    message: str
    session_id: str | None = None

@app.post("/v1/chat")
async def chat(
    body: ChatIn,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    user_id: str = Header("demo-user", alias="X-User-ID"),
):
    session_id = body.session_id or str(uuid4())
    runtime = OrchestrationRuntime.from_manifest(
        MANIFEST,
        run_context=RunContext(tenant_id=tenant_id, user_id=user_id, session_id=session_id),
    )
    result = await runtime.run(body.message)
    return {"session_id": session_id, "response": result.final_response}
```

**Same request for either app**

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "X-Tenant-ID: acme" -H "X-User-ID: user-42" \
  -H "Content-Type: application/json" \
  -d '{"message": "Look up account acme-99 and confirm the plan"}'
```

Full annotated options: [docs/assets/complete-manifest.annotated.yaml](docs/assets/complete-manifest.annotated.yaml), [docs/assets/research_team_prompts.annotated.py](docs/assets/research_team_prompts.annotated.py), [docs/assets/complete-run.annotated.py](docs/assets/complete-run.annotated.py), [docs/getting-started-python.md](docs/getting-started-python.md). Production SaaS (plan tiers, per-tenant storage): [examples/nexus_saas_api.py](examples/nexus_saas_api.py).

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
