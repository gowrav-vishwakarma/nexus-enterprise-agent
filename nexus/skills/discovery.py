"""Discover SKILL.md files in configured directories."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, Optional

from nexus.skills.models import FileSkill, SkillParseError
from nexus.skills.parser import parse_skill_md

logger = logging.getLogger(__name__)

_MAX_SCAN_DEPTH = 2


def discover_skills_in_path(
    root: Path,
    *,
    scope: Literal["global", "tenant", "user"] = "global",
    max_depth: int = _MAX_SCAN_DEPTH,
) -> list[FileSkill]:
    """Scan *root* for SKILL.md files up to *max_depth* levels deep."""
    root = root.resolve()
    if not root.is_dir():
        return []

    skills: list[FileSkill] = []
    seen_dirs: set[Path] = set()

    def _try_parse(skill_dir: Path) -> None:
        if skill_dir in seen_dirs:
            return
        seen_dirs.add(skill_dir)
        try:
            skills.append(parse_skill_md(skill_dir, scope=scope))
        except SkillParseError as exc:
            logger.warning("Skipping invalid skill at %s: %s", skill_dir, exc)

    # Direct children: skill-name/SKILL.md
    for child in sorted(root.iterdir()):
        if child.is_dir():
            skill_md = child / "SKILL.md"
            if skill_md.is_file():
                _try_parse(child)

    # One nested level: category/skill-name/SKILL.md
    if max_depth >= 2:
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            for nested in sorted(child.iterdir()):
                if nested.is_dir() and (nested / "SKILL.md").is_file():
                    _try_parse(nested)

    return skills


def discover_skills_from_paths(
    paths: list[Path],
    *,
    scope: Literal["global", "tenant", "user"] = "global",
) -> list[FileSkill]:
    """Discover skills from multiple root paths."""
    all_skills: list[FileSkill] = []
    for path in paths:
        all_skills.extend(discover_skills_in_path(path, scope=scope))
    return all_skills
