# Prompt templates and Jinja

**Who this is for:** Anyone writing `PROMPTS` in a prompts module or custom system prompt templates.

## Key terms

- **Jinja** — A template language with `{{ variable }}` placeholders.
- **PROMPTS** — Required dict in your prompts Python file: name → template string or callable.
- **Single render** — One Jinja pass per LLM turn resolves all variables (persona, run context, memory, summary).

## Prompts module contract

**Primary (recommended):** string templates with all `{{ }}` variables in one place.

```python
RESEARCHER_SYSTEM = """You are {{ role }} focused on {{ domain }}.

Goal: {{ goal }}

{% if tenant_id %}Tenant: {{ tenant_id }}{% endif %}

{% if user_memory %}
## About this user
{% for key, value in user_memory.items() %}
- {{ key }}: {{ value }}
{% endfor %}
{% endif %}

{% if summary_text %}
## Conversation Summary
{{ summary_text }}
{% endif %}

Today's date: {{ current_date }}
"""

PROMPTS = {
    "researcher_system": RESEARCHER_SYSTEM,
}
```

YAML references a key:

```yaml
persona:
  prompt: researcher_system
  prompt_args:
    domain: finance
```

Default prompts path: `{manifest_stem}_prompts.py` beside the YAML. Override with `prompts_module:`.

At manifest load, the framework stores the **raw** template string on `persona.system_prompt_template` (Jinja tags are not pre-rendered). Each LLM turn calls `render_system_prompt()` with the full variable set.

## Template variables (each LLM turn)

| Variable | Source |
|----------|--------|
| `role`, `goal`, `backstory` | YAML `persona` |
| `persona` | Full persona dict |
| `domain`, … | YAML `persona.prompt_args` (also available as top-level keys and as `prompt_args` dict) |
| `tenant_id`, `user_id`, `session_id`, `request_id` | `RunContext` + session |
| `metadata` | `RunContext.metadata` |
| `user_memory` | Cross-session facts (when `memory.enabled`) |
| `summary_text` | Rolling summary of folded turns (when `context_summary` enabled) |
| `current_date` | Today's date (YYYY-MM-DD) |

Within-chat message history is built from `session.turns`. `summary_text` holds narrative from turns that were folded when context filled up.

Both `user_memory` and `summary_text` are also appended by framework injectors when custom templates omit the Jinja blocks.

## Advanced: callable prompts

Callables are for cases where you need Python logic at **load time** to build a template string (for example, fixing `domain` from `prompt_args` into the template body). The callable must return an **unrendered Jinja template**, not final prose.

```python
def analyst_system(domain: str = "general", **ctx) -> str:
    return (
        f"You are {{{{ role }}}} for {domain}.\n"
        "{% if tenant_id %}Tenant: {{ tenant_id }}{% endif %}\n"
        "Goal: {{ goal }}\n"
    )

PROMPTS = {
    "analyst_system": analyst_system,
}
```

At load time the callable receives `role`, `goal`, `backstory`, `tenant_id`, and flattened `prompt_args`. Runtime variables like `user_memory` and `summary_text` are still resolved on each LLM turn.

Full example: [examples/orchestration/research_team_prompts.py](../../examples/orchestration/research_team_prompts.py).

## Enable memory and context summary

```yaml
defaults:
  agent:
    memory:
      enabled: true
    context_summary:
      summarize_on: 0.8
```

Also wire `cross_session_memory_store` on the runner and set `RunContext.user_id` for `user_memory`. See [memory reference](../reference/memory.md) and [context summary](../reference/context-summary.md).

## Next steps

- [Getting started (YAML)](../getting-started.md)
- [Manifest schema](../reference/manifest-schema.md)
