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

    def section_names(self) -> list[str]:
        """Return ``##`` heading slugs in document order (empty if none)."""
        return list(parse_skill_sections(self.content).keys())

    def format_load_response(self, section: str = "all") -> str:
        """Format the skill body for ``load_skill`` tool results.

        ``section="all"`` (default) returns the full SKILL.md body plus a
        resource/script index — the historical behaviour. Any other value
        returns only the matching ``##`` heading so the agent does not dump
        unused sections into context.
        """
        requested = (section or "all").strip() or "all"
        if requested.lower() != "all":
            sections = parse_skill_sections(self.content)
            body = lookup_skill_section(sections, requested)
            if body is None:
                available = ", ".join(sections) if sections else "(no ## headings)"
                return (
                    f"Error: section {requested!r} not found in skill "
                    f"{self.frontmatter.name!r}. Available: {available}"
                )
            lines = [
                f"# Skill: {self.frontmatter.name} (section: {requested})",
                "",
                body.strip(),
                "",
            ]
            return "\n".join(lines)

        lines = [
            f"# Skill: {self.frontmatter.name}",
            "",
            self.content.strip(),
            "",
        ]
        extra_sections = self.section_names()
        if extra_sections:
            lines.append("## Sections (request with load_skill section=...)")
            for name in extra_sections:
                lines.append(f"- {name}")
            lines.append("")
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


def parse_skill_sections(content: str) -> dict[str, str]:
    """Split a SKILL.md body into ``## heading`` sections.

    Keys are lowercase heading text with surrounding whitespace stripped.
    The value is the heading line plus the body until the next ``##``.
    A leading preamble before the first ``##`` is stored under ``_preamble``.
    """
    if not content:
        return {}
    lines = content.splitlines()
    sections: dict[str, list[str]] = {}
    current = "_preamble"
    sections[current] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("###"):
            current = stripped[3:].strip().lower()
            sections.setdefault(current, [])
            sections[current].append(line)
            continue
        sections.setdefault(current, []).append(line)
    return {
        key: "\n".join(body).strip()
        for key, body in sections.items()
        if "\n".join(body).strip() and key != "_preamble"
    }


def lookup_skill_section(sections: dict[str, str], name: str) -> Optional[str]:
    """Return a section body, matching case-insensitively and by slug."""
    needle = name.strip().lower()
    if needle in sections:
        return sections[needle]
    slug = needle.replace(" ", "-")
    for key, value in sections.items():
        if key.replace(" ", "-") == slug:
            return value
    return None


class SkillParseError(ValueError):
    """Raised when a SKILL.md file fails validation."""


class SkillNotFoundError(KeyError):
    """Raised when a requested skill name is not in the registry."""


class SkillResourceNotFoundError(KeyError):
    """Raised when a requested skill resource is not found."""


class SkillSecurityError(PermissionError):
    """Raised when a skill file access violates security policy."""
