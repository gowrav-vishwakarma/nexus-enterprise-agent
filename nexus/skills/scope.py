"""Skill scope resolver — decides what partitions a skill (tenant/company/user)."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from nexus.session.scope import SessionScope
from nexus.tools.context import RunContext


class SkillScopeConfig(BaseModel):
    """How to derive a skill partition key from RunContext.

    Examples:
    - ``keys=[]`` → global skills shared by everyone
    - ``keys=["tenant_id"]`` → per-tenant
    - ``keys=["tenant_id", "company_id"]`` → per-company
    - ``keys=["tenant_id", "company_id", "user_id"]`` → per-user
    """

    keys: list[str] = Field(
        default_factory=lambda: ["tenant_id", "company_id", "user_id"],
        description="Ordered RunContext fields that form the skill partition",
    )
    resolver_class: Optional[str] = Field(
        default=None,
        description="Optional import path for a custom SkillScopeResolver",
    )


@runtime_checkable
class SkillScopeResolver(Protocol):
    """Resolve a SessionScope used as the skill partition."""

    def resolve(self, ctx: RunContext) -> SessionScope: ...


class KeysSkillScopeResolver:
    """Declarative resolver: keep only the configured context fields."""

    def __init__(self, keys: list[str]):
        self.keys = keys

    def resolve(self, ctx: RunContext) -> SessionScope:
        data: dict[str, Any] = {}
        for field in self.keys:
            data[field] = getattr(ctx, field, None)
        return SessionScope(
            tenant_id=data.get("tenant_id"),
            company_id=data.get("company_id"),
            user_id=data.get("user_id"),
        )


def build_skill_scope_resolver(config: SkillScopeConfig) -> SkillScopeResolver:
    """Build a resolver from config (custom class or keys list)."""
    if config.resolver_class:
        module_path, _, name = config.resolver_class.rpartition(".")
        module = import_module(module_path)
        cls = getattr(module, name)
        return cls() if callable(cls) else cls
    return KeysSkillScopeResolver(config.keys)
