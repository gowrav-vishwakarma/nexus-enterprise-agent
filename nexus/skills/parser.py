"""Parse and validate SKILL.md files per agentskills.io specification."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from nexus.skills.models import FileSkill, SkillFrontmatter, SkillParseError, SkillResource, SkillScript

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _validate_name(name: str, directory_name: str) -> None:
    if not name or len(name) > 64:
        raise SkillParseError(f"Skill name must be 1-64 characters: {name!r}")
    if not _NAME_RE.match(name):
        raise SkillParseError(
            f"Skill name must be lowercase alphanumeric with hyphens: {name!r}"
        )
    if name != directory_name:
        raise SkillParseError(
            f"Skill name {name!r} must match parent directory {directory_name!r}"
        )


def _validate_description(description: Any) -> str:
    if not isinstance(description, str) or not description.strip():
        raise SkillParseError("Skill description is required and must be non-empty")
    if len(description) > 1024:
        raise SkillParseError("Skill description must be at most 1024 characters")
    return description.strip()


def parse_skill_md(skill_dir: Path, *, scope: str = "global") -> FileSkill:
    """Parse a skill directory containing SKILL.md."""
    skill_dir = skill_dir.resolve()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SkillParseError(f"SKILL.md not found in {skill_dir}")

    raw = skill_md.read_text(encoding="utf-8", errors="replace")
    frontmatter_raw, body = _split_frontmatter(raw)
    data = yaml.safe_load(frontmatter_raw) or {}
    if not isinstance(data, dict):
        raise SkillParseError("SKILL.md frontmatter must be a YAML mapping")

    name = data.get("name")
    if not isinstance(name, str):
        raise SkillParseError("SKILL.md frontmatter must include a string 'name' field")

    _validate_name(name, skill_dir.name)
    description = _validate_description(data.get("description"))

    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise SkillParseError("SKILL.md metadata must be a mapping")
    metadata = {str(k): str(v) for k, v in metadata.items()}

    frontmatter = SkillFrontmatter(
        name=name,
        description=description,
        license=data.get("license"),
        compatibility=data.get("compatibility"),
        allowed_tools=data.get("allowed-tools"),
        metadata=metadata,
    )

    resources = _discover_resources(skill_dir)
    scripts = _discover_scripts(skill_dir)

    return FileSkill(
        frontmatter=frontmatter,
        content=body.strip(),
        directory=skill_dir,
        resources=resources,
        scripts=scripts,
        scope=scope,  # type: ignore[arg-type]
    )


def _split_frontmatter(raw: str) -> tuple[str, str]:
    """Split YAML frontmatter from markdown body."""
    if not raw.startswith("---"):
        raise SkillParseError("SKILL.md must start with YAML frontmatter (---)")
    end = raw.find("\n---", 3)
    if end == -1:
        raise SkillParseError("SKILL.md frontmatter must be closed with ---")
    frontmatter = raw[3:end].strip()
    body = raw[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    return frontmatter, body


def _discover_resources(skill_dir: Path) -> list[SkillResource]:
    resources: list[SkillResource] = []
    for category in ("references", "assets"):
        subdir = skill_dir / category
        if not subdir.is_dir():
            continue
        for path in sorted(subdir.rglob("*")):
            if path.is_file() and path.name != ".gitkeep":
                rel = path.relative_to(skill_dir).as_posix()
                resources.append(
                    SkillResource(
                        name=path.stem if path.suffix else path.name,
                        relative_path=rel,
                        category=category,  # type: ignore[arg-type]
                    )
                )
    return resources


def _discover_scripts(skill_dir: Path) -> list[SkillScript]:
    scripts: list[SkillScript] = []
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return scripts
    for path in sorted(scripts_dir.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".sh", ".js") and path.name != ".gitkeep":
            rel = path.relative_to(scripts_dir).as_posix()
            scripts.append(
                SkillScript(
                    name=path.stem,
                    relative_path=rel,
                    full_path=path,
                )
            )
    return scripts
