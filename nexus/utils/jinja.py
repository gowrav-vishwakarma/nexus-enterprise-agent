"""Jinja2 template rendering for system prompts."""

from jinja2 import Environment, FileSystemLoader, BaseLoader, select_autoescape
from typing import Any, Optional


def render_system_prompt(
    persona: dict[str, Any],
    working_memory: str = "",
    entity_memory: Optional[dict[str, str]] = None,
    current_date: str = "",
    template: Optional[str] = None,
) -> str:
    """Render a system prompt from a persona dict and template.

    Args:
        persona: Dict with keys: role, goal, backstory, system_prompt_template
        working_memory: Current working memory content
        entity_memory: Dict of known facts/entities
        current_date: Current date string
        template: Optional custom template override

    Returns:
        Rendered system prompt string
    """
    if entity_memory is None:
        entity_memory = {}

    env = Environment(loader=BaseLoader(), autoescape=select_autoescape())
    tmpl_str = template or persona.get("system_prompt_template", "")
    template = env.from_string(tmpl_str)

    return template.render(
        persona=persona,
        working_memory=working_memory,
        entity_memory=entity_memory,
        current_date=current_date,
    )
