"""SkillStore — persist learned skills in memory, files, or a custom backend."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from nexus.session.scope import SessionScope


class SkillRecord(BaseModel):
    """One learned or manually managed skill."""

    name: str
    trigger: str = ""
    content: str = ""
    source: Literal["agentskills", "learned", "manual"] = "learned"
    enabled: bool = True
    use_count: int = 0
    updated_at: datetime = Field(default_factory=datetime.now)


def _normalize_name(name: str) -> str:
    cleaned = name.strip().lower().replace(" ", "_").replace("/", "__")
    return re.sub(r"[^a-z0-9_\-]+", "_", cleaned)[:200]


@runtime_checkable
class SkillStore(Protocol):
    """Protocol for learned-skill persistence."""

    async def search(
        self, scope: SessionScope, query: str, k: int = 6
    ) -> list[SkillRecord]: ...

    async def upsert(self, scope: SessionScope, skill: SkillRecord) -> SkillRecord: ...

    async def list(
        self, scope: SessionScope, *, include_disabled: bool = False
    ) -> list[SkillRecord]: ...

    async def delete(self, scope: SessionScope, name: str) -> None: ...

    async def disable(self, scope: SessionScope, name: str) -> None: ...

    async def get(
        self, scope: SessionScope, name: str
    ) -> Optional[SkillRecord]: ...


class InMemorySkillStore:
    """Dict-backed skill store (tests / single-process)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, SkillRecord]] = {}

    def _bucket(self, scope: SessionScope) -> str:
        parts = scope.path_segments()
        return "/".join(parts) if parts else "_global"

    async def search(
        self, scope: SessionScope, query: str, k: int = 6
    ) -> list[SkillRecord]:
        q = query.lower()
        matches = []
        for skill in await self.list(scope):
            hay = f"{skill.trigger} {skill.content}".lower()
            if q in hay or not q:
                skill.use_count += 1
                matches.append(skill)
        return matches[:k]

    async def upsert(self, scope: SessionScope, skill: SkillRecord) -> SkillRecord:
        skill.name = _normalize_name(skill.name)
        skill.updated_at = datetime.now()
        bucket = self._bucket(scope)
        self._data.setdefault(bucket, {})[skill.name] = skill
        return skill

    async def list(
        self, scope: SessionScope, *, include_disabled: bool = False
    ) -> list[SkillRecord]:
        bucket = self._bucket(scope)
        skills = list(self._data.get(bucket, {}).values())
        if not include_disabled:
            skills = [s for s in skills if s.enabled]
        return skills

    async def delete(self, scope: SessionScope, name: str) -> None:
        bucket = self._bucket(scope)
        self._data.get(bucket, {}).pop(_normalize_name(name), None)

    async def disable(self, scope: SessionScope, name: str) -> None:
        skill = await self.get(scope, name)
        if skill:
            skill.enabled = False
            skill.updated_at = datetime.now()

    async def get(
        self, scope: SessionScope, name: str
    ) -> Optional[SkillRecord]:
        bucket = self._bucket(scope)
        return self._data.get(bucket, {}).get(_normalize_name(name))


class FileSkillStore:
    """Write learned skills as agentskills.io-compatible SKILL.md folders."""

    def __init__(self, root: str | Path, *, scope_keys: Optional[list[str]] = None):
        self.root = Path(root)
        self.scope_keys = scope_keys or ["tenant_id", "company_id", "user_id"]
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, scope: SessionScope) -> Path:
        segments = scope.path_segments(keys=self.scope_keys)
        path = self.root.joinpath(*segments) if segments else self.root / "_global"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _skill_path(self, scope: SessionScope, name: str) -> Path:
        return self._dir(scope) / _normalize_name(name) / "SKILL.md"

    def _parse(self, path: Path) -> Optional[SkillRecord]:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        meta: dict[str, Any] = {}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip().strip("\"'")
                body = parts[2].strip()
        return SkillRecord(
            name=meta.get("name") or path.parent.name,
            trigger=meta.get("trigger", ""),
            content=body,
            source=meta.get("source", "learned"),  # type: ignore[arg-type]
            enabled=meta.get("enabled", "true").lower() != "false",
            use_count=int(meta.get("use_count", "0")),
        )

    def _write(self, path: Path, skill: SkillRecord) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        front = (
            "---\n"
            f"name: {skill.name}\n"
            f"trigger: {json.dumps(skill.trigger)}\n"
            f"source: {skill.source}\n"
            f"enabled: {str(skill.enabled).lower()}\n"
            f"use_count: {skill.use_count}\n"
            "---\n\n"
        )
        path.write_text(front + skill.content.strip() + "\n", encoding="utf-8")

    async def search(
        self, scope: SessionScope, query: str, k: int = 6
    ) -> list[SkillRecord]:
        q = query.lower()
        matches = []
        for skill in await self.list(scope):
            hay = f"{skill.trigger} {skill.content}".lower()
            if not q or q in hay:
                skill.use_count += 1
                self._write(self._skill_path(scope, skill.name), skill)
                matches.append(skill)
        return matches[:k]

    async def upsert(self, scope: SessionScope, skill: SkillRecord) -> SkillRecord:
        skill.name = _normalize_name(skill.name)
        skill.updated_at = datetime.now()
        self._write(self._skill_path(scope, skill.name), skill)
        return skill

    async def list(
        self, scope: SessionScope, *, include_disabled: bool = False
    ) -> list[SkillRecord]:
        base = self._dir(scope)
        skills: list[SkillRecord] = []
        for skill_md in base.glob("*/SKILL.md"):
            parsed = self._parse(skill_md)
            if parsed is None:
                continue
            if not include_disabled and not parsed.enabled:
                continue
            skills.append(parsed)
        return skills

    async def delete(self, scope: SessionScope, name: str) -> None:
        path = self._skill_path(scope, name)
        if path.exists():
            path.unlink()
            try:
                path.parent.rmdir()
            except OSError:
                pass

    async def disable(self, scope: SessionScope, name: str) -> None:
        skill = await self.get(scope, name)
        if skill:
            skill.enabled = False
            await self.upsert(scope, skill)

    async def get(
        self, scope: SessionScope, name: str
    ) -> Optional[SkillRecord]:
        return self._parse(self._skill_path(scope, name))


def build_learned_skills_block(skills: list[SkillRecord]) -> str:
    """Markdown block injected into the system prompt."""
    if not skills:
        return ""
    lines = ["## Learned Skills (apply these patterns where relevant)", ""]
    for skill in skills:
        lines.append(f"### {skill.name}")
        if skill.trigger:
            lines.append(f"**When**: {skill.trigger}")
        lines.append(f"**How**: {skill.content}")
        lines.append("")
    return "\n".join(lines).rstrip()
