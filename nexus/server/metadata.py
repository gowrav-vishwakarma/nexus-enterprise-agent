"""Propagate RunContext through gRPC metadata."""

from __future__ import annotations

from typing import Optional

from nexus.tools.context import RunContext

_TENANT = "x-tenant-id"
_USER = "x-user-id"
_SESSION = "x-session-id"
_REQUEST = "x-request-id"


def run_context_to_metadata(ctx: Optional[RunContext]) -> tuple[tuple[str, str], ...]:
    """Build gRPC metadata tuples from a RunContext."""
    if ctx is None:
        return ()
    pairs: list[tuple[str, str]] = []
    if ctx.tenant_id:
        pairs.append((_TENANT, ctx.tenant_id))
    if ctx.user_id:
        pairs.append((_USER, ctx.user_id))
    if ctx.session_id:
        pairs.append((_SESSION, ctx.session_id))
    if ctx.request_id:
        pairs.append((_REQUEST, ctx.request_id))
    return tuple(pairs)


def metadata_to_dict(metadata) -> dict[str, str]:
    """Parse gRPC servicer invocation metadata into a flat dict."""
    out: dict[str, str] = {}
    for key, value in metadata:
        k = key.decode() if isinstance(key, bytes) else str(key)
        v = value.decode() if isinstance(value, bytes) else str(value)
        out[k.lower()] = v
    return out
