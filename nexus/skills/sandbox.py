"""Skill script execution sandbox adapters."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from nexus.skills.models import FileSkill, SkillScript
from nexus.tools.context import RunContext


class SkillExecutionDisabledError(RuntimeError):
    """Raised when skill script execution is not enabled."""


@runtime_checkable
class SkillSandboxAdapter(Protocol):
    """Protocol for executing skill scripts in an isolated environment."""

    async def run_script(
        self,
        skill: FileSkill,
        script: SkillScript,
        args: Optional[list[str]] = None,
        *,
        run_context: RunContext,
    ) -> str:
        """Execute a skill script and return stdout/result text."""
        ...


class DisabledSkillSandbox:
    """Default sandbox that rejects all script execution (phase 1)."""

    async def run_script(
        self,
        skill: FileSkill,
        script: SkillScript,
        args: Optional[list[str]] = None,
        *,
        run_context: RunContext,
    ) -> str:
        raise SkillExecutionDisabledError(
            "Script execution is disabled. Enable allow_scripts and configure "
            "a SkillSandboxAdapter in SkillsConfig.sandbox_adapter."
        )


_SANDBOX_REGISTRY: dict[str, SkillSandboxAdapter] = {
    "disabled": DisabledSkillSandbox(),
}


def register_sandbox_adapter(name: str, adapter: SkillSandboxAdapter) -> None:
    """Register a named sandbox adapter."""
    _SANDBOX_REGISTRY[name] = adapter


def resolve_sandbox(adapter_name: Optional[str]) -> SkillSandboxAdapter:
    """Resolve a sandbox adapter by name; defaults to DisabledSkillSandbox."""
    if not adapter_name:
        return DisabledSkillSandbox()
    adapter = _SANDBOX_REGISTRY.get(adapter_name)
    if adapter is None:
        return DisabledSkillSandbox()
    return adapter
