"""Skills configuration model."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from nexus.skills.scope import SkillScopeConfig


def _default_global_paths() -> list[str]:
    """Default scan path from NEXUS_SKILLS_ROOT (or ./skills)."""
    from nexus.skills.paths import get_skills_root

    return [str(get_skills_root())]


class SkillsConfig(BaseModel):
    """Configuration for agent skills (agentskills.io + learned stores)."""

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
        description="Enable tenant-scoped static skill folders",
    )
    allow_user_skills: bool = Field(
        default=False,
        description="Enable user-scoped static skill folders",
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

    # Learned skills
    scope: SkillScopeConfig = Field(
        default_factory=SkillScopeConfig,
        description="Which RunContext fields partition learned skills",
    )
    store_backend: Literal["none", "memory", "file", "custom"] = Field(
        default="none",
        description="Where learned skills are persisted",
    )
    store_class: Optional[str] = Field(
        default=None,
        description="Import path when store_backend=custom",
    )
    store_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Backend kwargs (e.g. root path for file store)",
    )
    retrieval_k: int = Field(
        default=6,
        ge=1,
        description="Max learned skills injected per turn from search",
    )
    inject_learned: bool = Field(
        default=True,
        description="Inject relevant learned skills into the system prompt",
    )
    expose_manage_tools: bool = Field(
        default=False,
        description="Register skill_manage tools on the main agent",
    )
