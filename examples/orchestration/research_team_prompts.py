"""Prompt templates for the research_team orchestration example.

Two-pass Jinja rendering
------------------------
Pass 1 (orchestration init): ``role``, ``goal``, ``backstory``, ``tenant_id``,
``user_id``, ``session_id``, ``request_id``, ``metadata``, plus YAML ``prompt_args``.

Pass 2 (each LLM turn via ContextWindowBuilder): ``persona``, ``working_memory``,
``entity_memory``, ``cross_session_entity_memory``, ``current_date``.

Use ``{% raw %}...{% endraw %}`` around pass-2 blocks so pass-1 does not evaluate
them away when memory is still empty.
"""

# Pass-2 memory blocks — same variables as DEFAULT_SYSTEM_TEMPLATE in nexus/config/defaults.py
_PASS2_MEMORY_BLOCKS = """{% raw %}
{% if cross_session_entity_memory %}
## About this user (across conversations)
{% for key, value in cross_session_entity_memory.items() %}
- {{ key }}: {{ value }}
{% endfor %}
{% endif %}

{% if working_memory %}
## Your Working Notes
{{ working_memory }}
{% endif %}

{% if entity_memory %}
## Known Facts (this conversation)
{% for key, value in entity_memory.items() %}
- {{ key }}: {{ value }}
{% endfor %}
{% endif %}

Today's date: {{ current_date }}
{% endraw %}"""

RESEARCHER_SYSTEM = """You are {{ role }} focused on {{ domain }}.

Goal: {{ goal }}

{% if backstory %}
Background: {{ backstory }}
{% endif %}

{% if tenant_id %}Tenant: {{ tenant_id }}{% endif %}
{% if user_id %}User: {{ user_id }}{% endif %}
{% if session_id %}Session: {{ session_id }}{% endif %}

""" + _PASS2_MEMORY_BLOCKS

SUPERVISOR_SYSTEM = """You are {{ role }} — team supervisor for {{ domain }}.

Goal: {{ goal }}

Delegate work to specialists using delegate_to_* tools.

{% if tenant_id %}Tenant: {{ tenant_id }}{% endif %}
{% if user_id %}User: {{ user_id }}{% endif %}

""" + _PASS2_MEMORY_BLOCKS


def analyst_system(domain: str = "general", **ctx) -> str:
    """Callable prompt: pass-1 context via ``**ctx``, pass-2 blocks preserved in raw."""
    role = ctx.get("role", "Analyst")
    goal = ctx.get("goal", "Analyze findings")
    backstory = ctx.get("backstory")
    tenant_id = ctx.get("tenant_id")
    user_id = ctx.get("user_id")

    header = f"You are {role} for {domain}.\n\nGoal: {goal}\n"
    if backstory:
        header += f"\nBackground: {backstory}\n"
    if tenant_id:
        header += f"\nTenant: {tenant_id}\n"
    if user_id:
        header += f"User: {user_id}\n"
    return header + "\n" + _PASS2_MEMORY_BLOCKS


PROMPTS = {
    "researcher_system": RESEARCHER_SYSTEM,
    "analyst_system": analyst_system,
    "supervisor_system": SUPERVISOR_SYSTEM,
}
