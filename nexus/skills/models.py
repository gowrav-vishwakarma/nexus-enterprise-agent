"""Data models for Agent Skills (agentskills.io compatible)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SkillFrontmatter(BaseModel):
    """Parsed YAML frontmatter from SKILL.md."""

    name: str
    description: str
    license: Optional[str] = None
    compatibility: Optional[str] = None
    allowed_tools: Optional[str] = Field(None, alias="allowed-tools")
    metadata: dict[str, str] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class SkillResource(BaseModel):
    """A supplementary file bundled with a skill."""

    name: str
    relative_path: str
    category: Literal["references", "assets", "root"] = "references"


class SkillScript(BaseModel):
    """An executable script bundled with a skill."""

    name: str
    relative_path: str
    full_path: Path


class FileSkill(BaseModel):
    """A filesystem-backed skill discovered from a SKILL.md directory."""

    frontmatter: SkillFrontmatter
    content: str
    directory: Path
    resources: list[SkillResource] = Field(default_factory=list)
    scripts: list[SkillScript] = Field(default_factory=list)
    scope: Literal["global", "tenant", "user"] = "global"

    model_config = {"arbitrary_types_allowed": True}

    @property
    def name(self) -> str:
        return self.frontmatter.name

    def format_load_response(self) -> str:
        """Format the full skill body for load_skill tool results."""
        lines = [
            f"# Skill: {self.frontmatter.name}",
            "",
            self.content.strip(),
            "",
        ]
        if self.resources:
            lines.append("## Available Resources")
            for res in self.resources:
                lines.append(f"- {res.name} ({res.category}/{res.relative_path})")
            lines.append("")
        if self.scripts:
            lines.append("## Available Scripts")
            for script in self.scripts:
                lines.append(f"- {script.name} (scripts/{script.relative_path})")
            lines.append("")
        return "\n".join(lines)

    def format_explicit_block(self) -> str:
        """Format skill body for direct system-prompt injection."""
        return (
            f"## Skill: {self.frontmatter.name}\n\n"
            f"{self.content.strip()}\n"
        )


class SkillParseError(ValueError):
    """Raised when a SKILL.md file fails validation."""


class SkillNotFoundError(KeyError):
    """Raised when a requested skill name is not in the registry."""


class SkillResourceNotFoundError(KeyError):
    """Raised when a requested skill resource is not found."""


class SkillSecurityError(PermissionError):
    """Raised when a skill file access violates security policy."""
