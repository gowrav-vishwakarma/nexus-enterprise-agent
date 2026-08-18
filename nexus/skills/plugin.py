"""Skills tool plugin for progressive disclosure."""

from __future__ import annotations

from typing import Any, Optional

from nexus.skills.config import SkillsConfig
from nexus.skills.models import SkillNotFoundError, SkillSecurityError
from nexus.skills.sandbox import SkillExecutionDisabledError
from nexus.skills.registry import SkillsRegistry
from nexus.skills.sandbox import resolve_sandbox
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool, tool_plugin


@tool_plugin(name="skills")
class SkillsPlugin:
    """Tool plugin exposing load_skill, read_skill_resource, and run_skill_script."""

    def __init__(
        self,
        registry: SkillsRegistry,
        config: SkillsConfig,
        run_context: Optional[RunContext] = None,
    ):
        self.registry = registry
        self.config = config
        self.run_context = run_context

    @tool(
        name="load_skill",
        description=(
            "Load skill instructions by name. Pass section='all' (default) for the "
            "full SKILL.md, or a ## heading name (for example 'security') to load "
            "only that section."
        ),
    )
    def load_skill(self, skill_name: str, section: str = "all") -> str:
        """Return SKILL.md body (full or one ## section) and resource index."""
        try:
            skill = self.registry.get_skill(skill_name, self.run_context)
            return skill.format_load_response(section=section)
        except SkillNotFoundError as exc:
            return f"Error: {exc}"

    @tool(
        name="read_skill_resource",
        description=(
            "Read a supplementary file from a skill (references/, assets/, or root). "
            "Use the resource name exactly as listed by load_skill."
        ),
    )
    def read_skill_resource(self, skill_name: str, resource_name: str) -> str:
        """Return the text content of a skill resource."""
        try:
            return self.registry.read_resource(skill_name, resource_name, self.run_context)
        except SkillNotFoundError as exc:
            return f"Error: {exc}"
        except SkillSecurityError as exc:
            return f"Error: security violation — {exc}"
        except Exception as exc:
            return f"Error: {exc}"

    @tool(
        name="run_skill_script",
        description=(
            "Execute a script bundled with a skill. Only available when script "
            "execution is enabled and a sandbox adapter is configured."
        ),
        requires_approval=True,
    )
    async def run_skill_script(
        self,
        skill_name: str,
        script_name: str,
        args: Optional[list[str]] = None,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Execute a skill script via the configured sandbox adapter."""
        ctx = run_context or self.run_context
        if not self.config.allow_scripts:
            return (
                "Error: Script execution is disabled. Enable allow_scripts and configure "
                "a SkillSandboxAdapter in SkillsConfig.sandbox_adapter."
            )
        try:
            skill = self.registry.get_skill(skill_name, ctx)
            script = _find_script(skill, script_name)
            if script is None:
                return f"Error: Script {script_name!r} not found in skill {skill_name!r}"
            sandbox = resolve_sandbox(self.config.sandbox_adapter)
            return await sandbox.run_script(skill, script, args, run_context=ctx or RunContext())
        except SkillExecutionDisabledError as exc:
            return f"Error: {exc}"
        except SkillNotFoundError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error: {exc}"


def _find_script(skill: Any, script_name: str):
    for script in skill.scripts:
        if script.name == script_name or script.relative_path == script_name:
            return script
        if script.relative_path.endswith(f"/{script_name}.py"):
            return script
        if script.relative_path.endswith(f"/{script_name}"):
            return script
    return None


def create_skills_plugin(
    registry: SkillsRegistry,
    config: SkillsConfig,
    run_context: Optional[RunContext] = None,
) -> SkillsPlugin:
    """Factory for a configured SkillsPlugin instance."""
    return SkillsPlugin(registry=registry, config=config, run_context=run_context)
