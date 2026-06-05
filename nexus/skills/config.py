"""Skills configuration model."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


def _default_global_paths() -> list[str]:
    """Default scan path from NEXUS_SKILLS_ROOT (or ./skills)."""
    from nexus.skills.paths import get_skills_root

    return [str(get_skills_root())]


class SkillsConfig(BaseModel):
    """Configuration for agent skills (agentskills.io compatible)."""

    enabled: bool = False
    activation_mode: Literal["auto", "explicit", "both"] = "auto"
    global_paths: list[str] = Field(default_factory=_default_global_paths)
    explicit_skills: list[str] = Field(
        default_factory=list,
        description="Skill names to pre-load into the system prompt",
    )
    enabled_skills: Optional[list[str]] = Field(
        None,
        description="Allowlist of skill names; None means all discovered skills",
    )
    allow_tenant_skills: bool = Field(
        default=False,
        description="Enable tenant-scoped skills (phase 2)",
    )
    allow_user_skills: bool = Field(
        default=False,
        description="Enable user-scoped skills (phase 2)",
    )
    allow_scripts: bool = Field(
        default=False,
        description="Allow run_skill_script tool execution",
    )
    require_script_approval: bool = Field(
        default=True,
        description="Require approval before script execution (future)",
    )
    sandbox_adapter: Optional[str] = Field(
        None,
        description="Name of SkillSandboxAdapter implementation to use",
    )
