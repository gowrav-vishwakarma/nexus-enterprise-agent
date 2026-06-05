"""Prompt templates for the research_team orchestration example.

Single-pass Jinja rendering
---------------------------
All variables are resolved in one render per LLM turn: ``role``, ``goal``,
``backstory``, ``prompt_args`` (e.g. ``domain``), ``tenant_id``, ``user_id``,
``session_id``, ``request_id``, ``metadata``, ``user_memory``, ``summary_text``,
and ``current_date``.
"""

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


def analyst_system(domain: str = "general", **ctx) -> str:
    """Callable prompt (advanced): returns a Jinja template with domain fixed at load time."""
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


PROMPTS = {
    "researcher_system": RESEARCHER_SYSTEM,
    "analyst_system": analyst_system,
    "supervisor_system": SUPERVISOR_SYSTEM,
}
