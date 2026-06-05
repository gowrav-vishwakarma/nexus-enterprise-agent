"""Annotated prompts module — every PROMPTS field explained.

Companion to complete-manifest.annotated.yaml. The runnable copy lives at
examples/orchestration/research_team_prompts.py.

Contract
--------
Your prompts file must define a dict named ``PROMPTS``:

    PROMPTS = {
        "some_key": "Jinja template string",
        "other_key": callable_that_returns_jinja_string,
    }

In YAML, reference a key under ``persona.prompt``:

    persona:
      prompt: researcher_system
      prompt_args:
        domain: finance

The framework stores the raw template at load time and renders it once per LLM
turn with role, goal, prompt_args, tenant_id, user_memory, summary_text, etc.
See docs/guides/prompts-jinja.md.
"""

from __future__ import annotations

# ── String templates (recommended) ───────────────────────────────────────────
# Use {{ variable }} for values resolved each LLM turn.
# Use {% if %} / {% for %} for optional blocks (memory, summary).

RESEARCHER_SYSTEM = """You are {{ role }} focused on {{ domain }}.

Goal: {{ goal }}

{% if backstory %}
Background: {{ backstory }}
{% endif %}

{% if tenant_id %}Tenant: {{ tenant_id }}{% endif %}
{% if user_id %}User: {{ user_id }}{% endif %}
{% if session_id %}Session: {{ session_id }}{% endif %}

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
# domain — from persona.prompt_args in YAML (also available as top-level Jinja var)
# role, goal, backstory — from persona block in YAML
# tenant_id, user_id, session_id, request_id — from RunContext per request
# user_memory — cross-session facts when memory.enabled
# summary_text — folded turn summary when context_summary is enabled
# current_date — today's date (YYYY-MM-DD), added by the framework


SUPERVISOR_SYSTEM = """You are {{ role }} — team supervisor for {{ domain }}.

Goal: {{ goal }}

Delegate work to specialists using delegate_to_* tools.

{% if tenant_id %}Tenant: {{ tenant_id }}{% endif %}
{% if user_id %}User: {{ user_id }}{% endif %}

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


# ── Callable template (advanced) ─────────────────────────────────────────────
# Return an unrendered Jinja string. Use when load-time Python logic should
# bake values into the template body (here: domain from prompt_args).
# At load time the callable receives role, goal, backstory, tenant_id, and
# flattened prompt_args. Runtime vars (user_memory, summary_text) still render
# on each LLM turn.


def analyst_system(domain: str = "general", **ctx) -> str:
    """Callable prompt: domain fixed at manifest load; rest rendered each turn."""
    return (
        f"You are {{{{ role }}}} for {domain}.\n\n"
        "Goal: {{ goal }}\n"
        "{% if backstory %}\nBackground: {{ backstory }}\n{% endif %}"
        "{% if tenant_id %}\nTenant: {{ tenant_id }}\n{% endif %}"
        "{% if user_id %}User: {{ user_id }}\n{% endif %}"
        "{% if user_memory %}\n## About this user\n"
        "{% for key, value in user_memory.items() %}\n- {{ key }}: {{ value }}\n"
        "{% endfor %}\n{% endif %}"
        "{% if summary_text %}\n## Conversation Summary\n{{ summary_text }}\n{% endif %}"
        "\nToday's date: {{ current_date }}\n"
    )


# PROMPTS (required) — maps YAML persona.prompt keys to template string or callable
PROMPTS = {
    "researcher_system": RESEARCHER_SYSTEM,   # persona.prompt: researcher_system
    "analyst_system": analyst_system,         # persona.prompt: analyst_system
    "supervisor_system": SUPERVISOR_SYSTEM,   # persona.prompt: supervisor_system
}
