"""skill_manage tool plugin for learned SkillStore entries."""

from __future__ import annotations

import json
from typing import Optional

from nexus.skills.scope import SkillScopeResolver
from nexus.skills.store import SkillRecord, SkillStore
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool, tool_plugin


@tool_plugin(name="skill_manage")
class SkillManagePlugin:
    """CRUD tools for learned skills."""

    def __init__(self, store: SkillStore, scope_resolver: SkillScopeResolver):
        self._store = store
        self._scope_resolver = scope_resolver

    def _scope(self, ctx: Optional[RunContext]):
        if ctx is None:
            from nexus.session.scope import SessionScope

            return SessionScope()
        return self._scope_resolver.resolve(ctx)

    @tool(name="upsert", description="Create or update a learned skill.")
    async def upsert(
        self,
        name: str,
        trigger: str,
        content: str,
        ctx: Optional[RunContext] = None,
    ) -> str:
        if ctx is not None and not ctx.should_persist:
            return json.dumps({"ok": True, "skipped": True, "reason": "non-persistable"})
        skill = SkillRecord(
            name=name,
            trigger=trigger,
            content=content,
            source="learned" if (ctx and ctx.is_subagent) else "manual",
        )
        saved = await self._store.upsert(self._scope(ctx), skill)
        return json.dumps({"ok": True, "name": saved.name})

    @tool(name="list", description="List learned skills for the current scope.")
    async def list_skills(
        self,
        include_disabled: bool = False,
        ctx: Optional[RunContext] = None,
    ) -> str:
        skills = await self._store.list(
            self._scope(ctx), include_disabled=include_disabled
        )
        return json.dumps(
            {
                "ok": True,
                "skills": [
                    {
                        "name": s.name,
                        "trigger": s.trigger,
                        "enabled": s.enabled,
                        "source": s.source,
                        "use_count": s.use_count,
                    }
                    for s in skills
                ],
            }
        )

    @tool(name="delete", description="Delete a learned skill by name.")
    async def delete(self, name: str, ctx: Optional[RunContext] = None) -> str:
        if ctx is not None and not ctx.should_persist:
            return json.dumps({"ok": True, "skipped": True})
        await self._store.delete(self._scope(ctx), name)
        return json.dumps({"ok": True, "name": name})

    @tool(name="disable", description="Soft-disable a learned skill.")
    async def disable(self, name: str, ctx: Optional[RunContext] = None) -> str:
        if ctx is not None and not ctx.should_persist:
            return json.dumps({"ok": True, "skipped": True})
        await self._store.disable(self._scope(ctx), name)
        return json.dumps({"ok": True, "name": name, "enabled": False})


def create_skill_manage_plugin(
    store: SkillStore, scope_resolver: SkillScopeResolver
) -> SkillManagePlugin:
    return SkillManagePlugin(store, scope_resolver)
