RESEARCHER_SYSTEM = """You are a {{ role }} focused on {{ domain }}.
{% if tenant_id %}Tenant: {{ tenant_id }}{% endif %}
Goal: {{ goal }}
"""


def analyst_system(domain: str = "general", **ctx) -> str:
    """Callable prompt (advanced): returns a Jinja template with domain fixed at load time."""
    return (
        f"You are an analyst for {domain}.\n"
        "{% if tenant_id %}Tenant={{ tenant_id }}{% endif %}\n"
        "Goal: {{ goal }}\n"
    )


PROMPTS = {
    "researcher_system": RESEARCHER_SYSTEM,
    "analyst_system": analyst_system,
}
