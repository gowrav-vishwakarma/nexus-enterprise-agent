"""Skills registry: discovery, caching, and scope resolution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from nexus.skills.config import SkillsConfig
from nexus.skills.discovery import discover_skills_from_paths
from nexus.skills.models import (
    FileSkill,
    SkillNotFoundError,
    SkillResourceNotFoundError,
    SkillSecurityError,
)
from nexus.skills.paths import global_skills_dir, tenant_skills_dir, user_skills_dir
from nexus.skills.security import safe_read_text, validate_resource_path
from nexus.tools.context import RunContext

logger = logging.getLogger(__name__)


class SkillsRegistry:
    """Discovers, caches, and resolves skills for a run."""

    def __init__(self, config: SkillsConfig):
        self.config = config
        self._cache: Optional[dict[str, FileSkill]] = None

    def _resolve_source_paths(self, run_context: Optional[RunContext] = None) -> list[tuple[Path, str]]:
        """Return (path, scope) pairs to scan. Phase 1: global only."""
        paths: list[tuple[Path, str]] = []
        for p in self.config.global_paths:
            paths.append((Path(p), "global"))

        if run_context and self.config.allow_tenant_skills and run_context.tenant_id:
            paths.append((tenant_skills_dir(run_context.tenant_id), "tenant"))

        if (
            run_context
            and self.config.allow_user_skills
            and run_context.tenant_id
            and run_context.user_id
        ):
            paths.append((user_skills_dir(run_context.tenant_id, run_context.user_id), "user"))

        return paths

    def discover(self, run_context: Optional[RunContext] = None, *, force: bool = False) -> dict[str, FileSkill]:
        """Discover skills and return name -> skill mapping with scope precedence."""
        if self._cache is not None and not force:
            return self._cache

        merged: dict[str, FileSkill] = {}
        for path, scope in self._resolve_source_paths(run_context):
            for skill in discover_skills_from_paths([path], scope=scope):  # type: ignore[arg-type]
                merged[skill.name] = skill

        if self.config.enabled_skills is not None:
            allow = set(self.config.enabled_skills)
            merged = {k: v for k, v in merged.items() if k in allow}

        self._cache = merged
        return merged

    def get_skill(self, name: str, run_context: Optional[RunContext] = None) -> FileSkill:
        """Return a skill by name."""
        skills = self.discover(run_context)
        if name not in skills:
            raise SkillNotFoundError(f"Skill not found: {name}")
        return skills[name]

    def list_skills(self, run_context: Optional[RunContext] = None) -> list[FileSkill]:
        """Return all available skills."""
        return list(self.discover(run_context).values())

    def read_resource(
        self,
        skill_name: str,
        resource_name: str,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Read a skill resource by name."""
        skill = self.get_skill(skill_name, run_context)
        resource = _find_resource(skill, resource_name)
        if resource is None:
            raise SkillResourceNotFoundError(
                f"Resource {resource_name!r} not found in skill {skill_name!r}"
            )
        try:
            resolved = validate_resource_path(skill.directory, Path(resource.relative_path))
            return safe_read_text(resolved)
        except ValueError as exc:
            raise SkillSecurityError(str(exc)) from exc

    def resolve_explicit_skills(
        self,
        run_context: Optional[RunContext] = None,
    ) -> list[FileSkill]:
        """Resolve skills to pre-load from config and run context metadata."""
        names: list[str] = list(self.config.explicit_skills)
        if run_context and run_context.metadata.get("skills"):
            raw = run_context.metadata["skills"]
            if isinstance(raw, str):
                names.append(raw)
            elif isinstance(raw, list):
                names.extend(str(s) for s in raw)

        seen: set[str] = set()
        result: list[FileSkill] = []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            try:
                result.append(self.get_skill(name, run_context))
            except SkillNotFoundError:
                logger.warning("Explicit skill %r not found; skipping", name)
        return result

    def has_scripts(self, run_context: Optional[RunContext] = None) -> bool:
        """Return True if any discovered skill has scripts."""
        return any(s.scripts for s in self.list_skills(run_context))

    def invalidate_cache(self) -> None:
        """Clear the discovery cache."""
        self._cache = None


def _find_resource(skill: FileSkill, resource_name: str):
    """Match resource by name or relative path."""
    for res in skill.resources:
        if res.name == resource_name or res.relative_path == resource_name:
            return res
        if res.relative_path.endswith(f"/{resource_name}"):
            return res
    return None
