"""Jinja2 template rendering for system prompts."""

from __future__ import annotations

from typing import Any, Optional

from jinja2 import BaseLoader, Environment, select_autoescape


def build_system_prompt_render_vars(
    persona: dict[str, Any],
    *,
    user_memory: Optional[dict[str, str]] = None,
    summary_text: str = "",
    current_date: str = "",
    run_context: Any = None,
    session: Any = None,
    extra_vars: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build the full Jinja context for a single system-prompt render."""
    if user_memory is None:
        user_memory = {}

    prompt_args = persona.get("prompt_args") or {}
    if not isinstance(prompt_args, dict):
        prompt_args = {}

    tenant_id = getattr(run_context, "tenant_id", None) if run_context else None
    user_id = getattr(run_context, "user_id", None) if run_context else None
    session_id = getattr(run_context, "session_id", None) if run_context else None
    request_id = getattr(run_context, "request_id", None) if run_context else None
    metadata = dict(getattr(run_context, "metadata", None) or {}) if run_context else {}

    if session is not None:
        tenant_id = tenant_id or getattr(session, "tenant_id", None)
        user_id = user_id or getattr(session, "user_id", None)
        session_id = session_id or getattr(session, "session_id", None)

    render_vars: dict[str, Any] = {
        "persona": persona,
        "role": persona.get("role"),
        "goal": persona.get("goal"),
        "backstory": persona.get("backstory"),
        "prompt_args": prompt_args,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "session_id": session_id,
        "request_id": request_id,
        "metadata": metadata,
        "user_memory": user_memory,
        "summary_text": summary_text,
        "current_date": current_date,
    }
    render_vars.update(prompt_args)
    if extra_vars:
        render_vars.update(extra_vars)
    return render_vars


def render_system_prompt(
    persona: dict[str, Any],
    user_memory: Optional[dict[str, str]] = None,
    summary_text: str = "",
    current_date: str = "",
    template: Optional[str] = None,
    run_context: Any = None,
    session: Any = None,
    extra_vars: Optional[dict[str, Any]] = None,
) -> str:
    """Render a system prompt from a persona dict and template.

    All variables (persona, prompt_args, run context, user_memory, summary_text)
    are resolved in a single Jinja render per LLM turn.
    """
    env = Environment(loader=BaseLoader(), autoescape=select_autoescape())
    tmpl_str = template or persona.get("system_prompt_template", "")
    jinja_template = env.from_string(tmpl_str)

    render_vars = build_system_prompt_render_vars(
        persona,
        user_memory=user_memory,
        summary_text=summary_text,
        current_date=current_date,
        run_context=run_context,
        session=session,
        extra_vars=extra_vars,
    )
    return jinja_template.render(**render_vars)
