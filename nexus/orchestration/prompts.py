"""Prompt module loading and two-pass Jinja resolution."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import Any, Callable

from jinja2 import BaseLoader, Environment, select_autoescape

from nexus.orchestration.errors import ManifestLoadError, PromptNotFoundError
from nexus.tools.context import RunContext

PromptValue = str | Callable[..., str]


def load_prompts_module(module_path: Path) -> dict[str, PromptValue]:
    """Load a prompts module and return its required ``PROMPTS`` registry."""
    if not module_path.is_file():
        raise ManifestLoadError(f"Prompts module not found: {module_path}")

    spec = importlib.util.spec_from_file_location(
        f"nexus_orchestration_prompts_{module_path.stem}",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise ManifestLoadError(f"Unable to import prompts module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    prompts = getattr(module, "PROMPTS", None)
    if not isinstance(prompts, dict):
        raise ManifestLoadError(
            f"Prompts module {module_path} must define a dict named PROMPTS"
        )
    return prompts


def build_prompt_context(
    *,
    persona: dict[str, Any],
    prompt_args: dict[str, Any],
    run_context: RunContext,
) -> dict[str, Any]:
    """Build the pass-1 Jinja/callable context for prompt resolution."""
    context: dict[str, Any] = {
        "role": persona.get("role"),
        "goal": persona.get("goal"),
        "backstory": persona.get("backstory"),
        "tenant_id": run_context.tenant_id,
        "user_id": run_context.user_id,
        "session_id": run_context.session_id,
        "request_id": run_context.request_id,
        "metadata": dict(run_context.metadata),
    }
    context.update(prompt_args)
    return context


def resolve_prompt_template(
    prompts: dict[str, PromptValue],
    prompt_name: str,
    *,
    persona: dict[str, Any],
    prompt_args: dict[str, Any] | None = None,
    run_context: RunContext,
) -> str:
    """Resolve a prompt reference to a pass-1 rendered system prompt template."""
    if prompt_name not in prompts:
        raise PromptNotFoundError(prompt_name, list(prompts.keys()))

    prompt_value = prompts[prompt_name]
    context = build_prompt_context(
        persona=persona,
        prompt_args=prompt_args or {},
        run_context=run_context,
    )

    if callable(prompt_value):
        template_str = _invoke_prompt_callable(prompt_value, context)
    elif isinstance(prompt_value, str):
        template_str = prompt_value
    else:
        raise ManifestLoadError(
            f"Prompt {prompt_name!r} must be a string or callable, got {type(prompt_value)!r}"
        )

    return _render_pass_one(template_str, context)


def resolve_persona_config(
    persona_data: dict[str, Any],
    *,
    prompts: dict[str, PromptValue],
    run_context: RunContext,
) -> dict[str, Any]:
    """Resolve persona block, applying prompt refs when present."""
    persona = dict(persona_data)
    prompt_name = persona.pop("prompt", None)
    prompt_args = persona.pop("prompt_args", None) or {}

    if prompt_name is not None:
        rendered = resolve_prompt_template(
            prompts,
            prompt_name,
            persona=persona,
            prompt_args=prompt_args if isinstance(prompt_args, dict) else {},
            run_context=run_context,
        )
        persona["system_prompt_template"] = rendered

    return persona


def _invoke_prompt_callable(fn: Callable[..., str], context: dict[str, Any]) -> str:
    signature = inspect.signature(fn)
    accepts_kwargs = any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )
    if accepts_kwargs:
        return fn(**context)
    filtered = {
        key: value
        for key, value in context.items()
        if key in signature.parameters
    }
    return fn(**filtered)


def _render_pass_one(template_str: str, context: dict[str, Any]) -> str:
    env = Environment(loader=BaseLoader(), autoescape=select_autoescape())
    template = env.from_string(template_str)
    return template.render(**context)
