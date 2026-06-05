# Examples index

**Who this is for:** Developers looking for runnable code beyond the getting-started guides.

## Key terms

- **Example** — A script or config in the `examples/` folder you can run or copy.
- **Fixture** — Test data under `tests/fixtures/` used by pytest.

## Orchestration (YAML)

| Path | What you will learn |
|------|---------------------|
| [examples/orchestration/research_team.yaml](../examples/orchestration/research_team.yaml) | Supervisor + nested pipeline team |
| [examples/orchestration/research_team_prompts.py](../examples/orchestration/research_team_prompts.py) | PROMPTS dict, Jinja templates |
| [examples/orchestration/run_team.py](../examples/orchestration/run_team.py) | CLI to load manifest and run |

```bash
uv run python examples/orchestration/run_team.py "Your question here"
```

Annotated references (not runnable as-is):

- [assets/complete-manifest.annotated.yaml](assets/complete-manifest.annotated.yaml)
- [assets/research_team_prompts.annotated.py](assets/research_team_prompts.annotated.py)
- [assets/complete-run.annotated.py](assets/complete-run.annotated.py)

## SaaS API

| Path | What you will learn |
|------|---------------------|
| [examples/nexus_saas_api.py](../examples/nexus_saas_api.py) | FastAPI multi-tenant app, plan gating, streaming |

Guide: [guides/saas-example.md](guides/saas-example.md).

## Python API (annotated)

| Path | What you will learn |
|------|---------------------|
| [assets/complete-agent.annotated.py](assets/complete-agent.annotated.py) | Every AgentConfig and AgentRunner parameter |

Walkthrough: [getting-started-python.md](getting-started-python.md).

## Test fixtures (orchestration)

Under `tests/fixtures/orchestration/`:

| File | What it tests |
|------|---------------|
| `basic.yaml` | Minimal single agent |
| `nested.yaml` | Nested groups |
| `parallel.yaml` | Parallel pattern fallback |
| `cycle.yaml` | Cycle detection error |

## Next steps

- [Getting started (YAML)](getting-started.md)
- [Documentation index](index.md)
