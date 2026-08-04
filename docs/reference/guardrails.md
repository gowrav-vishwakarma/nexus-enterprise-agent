# Guardrails (`nexus[guardrails]`)

Input/output guards run on runner hooks.

## Built-in guards

| Guard | Behavior |
|-------|----------|
| `PIIRedactionGuard` | Redacts emails and phone numbers |
| `PromptInjectionGuard` | Blocks obvious injection phrases on input |

## Usage

```python
from nexus.guardrails import GuardEngine, PIIRedactionGuard, PromptInjectionGuard
from nexus.runner.hooks import RunnerHooks

engine = GuardEngine([PIIRedactionGuard(), PromptInjectionGuard()])

async def before_llm_call(ctx):
    result = await engine.check_input(ctx.messages[-1]["content"], ctx.run_context)
    if result.decision.value == "block":
        raise GuardrailError(result.reason)
    return None

hooks = RunnerHooks(before_llm_call=before_llm_call)
```

## Tool policy & cost

- `ToolPolicyEngine.from_context(ctx)` — allow/deny from `ctx.auth`
- `CostTracker` — token and USD estimates
- `RateLimiter` — per-tenant requests/minute
- `AuditSink` — append-only audit log; register it on the emitter with the run's
  `RunContext` so lines are scope-keyed. See
  [events.md](events.md#audit-trail).

## Redaction

`PIIRedactionGuard` strips email addresses and phone numbers from model-facing
content. The same patterns live in
[nexus/guardrails/redaction.py](../../nexus/guardrails/redaction.py) and back
`RedactingEventSink`, so data removed from a prompt is also removed from traces and
webhooks. Use `redact_text()` for strings and `redact_payload()` for nested
dicts and lists in your own code.

See also [events.md](events.md) for `human_in_loop.*` events (now emitted by the runner).
