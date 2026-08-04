"""Unified scope primitive for tenant / company / user / global resources.

Every scoped subsystem (memory, skills, storage, RAG, guardrails, quotas)
uses the same key derivation so multi-tenant isolation is consistent.
"""

from __future__ import annotations

from enum import Enum

from nexus.session.scope import SessionScope
from nexus.tools.context import RunContext


class ScopeLevel(str, Enum):
    """Isolation level for a resource."""

    GLOBAL = "global"
    TENANT = "tenant"
    COMPANY = "company"
    USER = "user"


# Ordered from broadest to narrowest for prefix building.
_SCOPE_FIELD_ORDER: tuple[tuple[ScopeLevel, str], ...] = (
    (ScopeLevel.TENANT, "tenant_id"),
    (ScopeLevel.COMPANY, "company_id"),
    (ScopeLevel.USER, "user_id"),
)

# Stands in for a field the context did not supply. Every level always emits a
# segment so a narrower level can never collapse onto a broader one's key.
_MISSING = "_"


def scope_key(
    ctx: RunContext,
    level: ScopeLevel,
    namespace: str = "",
) -> str:
    """Build a stable scope key string for storage and indexing.

    Each level emits its own segment even when the context left that field
    empty, so a user-scoped key can never collapse onto the tenant-scoped key
    and leak one user's data to the whole tenant.

    Examples:
        scope_key(ctx, ScopeLevel.TENANT, "skills") -> "tenant:acme:skills"
        scope_key(ctx, ScopeLevel.USER, "memory") -> "tenant:acme:company:co1:user:u1:memory"
        scope_key(tenant_only_ctx, ScopeLevel.USER) -> "tenant:acme:company:_:user:_"
    """
    if level == ScopeLevel.GLOBAL:
        base = "global"
    else:
        segments: list[str] = []
        for scope_level, field in _SCOPE_FIELD_ORDER:
            value = getattr(ctx, field, None)
            text = str(value).strip() if value is not None else ""
            segments.extend([scope_level.value, text or _MISSING])
            if scope_level == level:
                break
        base = ":".join(segments)
    if namespace:
        return f"{base}:{namespace}"
    return base


def scope_from_keys(keys: list[str]) -> ScopeLevel:
    """Infer the broadest scope level from a list of RunContext field names."""
    if not keys:
        return ScopeLevel.GLOBAL
    if "user_id" in keys:
        return ScopeLevel.USER
    if "company_id" in keys:
        return ScopeLevel.COMPANY
    if "tenant_id" in keys:
        return ScopeLevel.TENANT
    return ScopeLevel.GLOBAL


def session_scope_from_level(ctx: RunContext, level: ScopeLevel) -> SessionScope:
    """Return a SessionScope truncated to the requested isolation level."""
    if level == ScopeLevel.GLOBAL:
        return SessionScope()
    return SessionScope(
        tenant_id=ctx.tenant_id if level.value in ("tenant", "company", "user") else None,
        company_id=ctx.company_id if level.value in ("company", "user") else None,
        user_id=ctx.user_id if level == ScopeLevel.USER else None,
    )


def scope_keys_from_config(keys: list[str], ctx: RunContext, namespace: str = "") -> str:
    """Build a scope key from an explicit list of RunContext attribute names.

    Used by skills and memory configs that declare ``keys=["tenant_id", "user_id"]``.
    """
    if not keys:
        return scope_key(ctx, ScopeLevel.GLOBAL, namespace)
    parts: list[str] = []
    for key in keys:
        value = getattr(ctx, key, None)
        if value is not None and str(value).strip():
            parts.extend([key, str(value).strip()])
    base = ":".join(parts) if parts else "global"
    if namespace:
        return f"{base}:{namespace}"
    return base
