RESEARCHER_SYSTEM = """You are a {{ role }} focused on {{ domain }}.
{% if tenant_id %}Tenant: {{ tenant_id }}{% endif %}
Goal: {{ goal }}
"""

def analyst_system(domain: str = "general", **ctx) -> str:
    tenant = ctx.get("tenant_id") or "unknown"
    return f"You are an analyst for {domain}. Tenant={tenant}"

PROMPTS = {
    "researcher_system": RESEARCHER_SYSTEM,
    "analyst_system": analyst_system,
}
