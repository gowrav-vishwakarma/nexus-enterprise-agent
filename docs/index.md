# Nexus documentation

**Who this is for:** Developers building chat agents or multi-agent teams with Nexus, including SaaS (software as a service) apps with many customers.

## Key terms

- **Agent** — A program that talks to a large language model (LLM) and can call **tools** (small programs the model can trigger).
- **Config** — Settings that describe what an agent is (model, personality, limits).
- **Run context** — Settings that describe who is calling and which chat thread this is.
- **Manifest** — A YAML file that describes one or more agents and how they work together.
- **Orchestration** — Loading a manifest and running the described agents.
- **Runner** — The object that executes one agent loop (`run()` or `run_stream()`).
- **Storage** — Where chat history is saved (memory, file, SQLite, PostgreSQL, Redis).

## What is Nexus?

Nexus is an agent framework for building production apps. You describe agents in config. You wire who is calling and where data lives at run time. Then you call `run()`.

There is no global settings object. Each agent can use a different LLM (large language model) provider. Storage and tenant (customer) identity are explicit.

## Reading order

1. [Architecture](architecture.md) — What goes where (config vs run time).
2. [Getting started (YAML)](getting-started.md) — Fastest path: manifest + prompts + run.
3. [Getting started (Python)](getting-started-python.md) — Build everything in code.
4. [Reference](reference/manifest-schema.md) — Every parameter and default.
5. [Guides](guides/saas-example.md) — Multi-tenant SaaS example and advanced topics.

```mermaid
flowchart TD
  index[docs/index.md]
  arch[architecture.md]
  yaml[get-started YAML]
  py[get-started Python]
  ref[reference/*]
  guides[guides/*]

  index --> arch
  arch --> yaml
  arch --> py
  yaml --> ref
  py --> ref
  ref --> guides
```

## Quick links

| Topic | Doc |
|-------|-----|
| YAML manifest fields | [reference/manifest-schema.md](reference/manifest-schema.md) |
| Agent config | [reference/agent-config.md](reference/agent-config.md) |
| Runner and runtime | [reference/agent-runner.md](reference/agent-runner.md) |
| Who is calling | [reference/run-context.md](reference/run-context.md) |
| Save chat history | [reference/storage.md](reference/storage.md) |
| Tools | [reference/tools.md](reference/tools.md) |
| Memory | [reference/memory.md](reference/memory.md) |
| Context summary | [reference/context-summary.md](reference/context-summary.md) |
| Multi-agent teams | [reference/multi-agent.md](reference/multi-agent.md) |
| Streaming | [reference/streaming.md](reference/streaming.md) |
| Skills | [reference/skills.md](reference/skills.md) |
| Environment variables | [reference/environment.md](reference/environment.md) |
| SaaS example | [guides/saas-example.md](guides/saas-example.md) |
| Prompt templates | [guides/prompts-jinja.md](guides/prompts-jinja.md) |
| Example index | [examples.md](examples.md) |
| Writing style | [style-guide.md](style-guide.md) |
| Full design spec | [NEXUS_AGENT_PRD.md](../NEXUS_AGENT_PRD.md) |

## Install

From PyPI:

```bash
pip install nexus-enterprise-agent
```

With extras (see [storage](reference/storage.md) and [environment](reference/environment.md)):

```bash
pip install "nexus-enterprise-agent[sqlite,litellm,fastapi]"
```

For local development:

```bash
uv sync --extra dev --extra sqlite --extra file
```

For the SaaS API example:

```bash
uv sync --extra fastapi --extra sqlite --extra litellm
```

Run tests:

```bash
uv run pytest
```
