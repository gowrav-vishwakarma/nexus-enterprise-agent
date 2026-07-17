"""Resolve media server endpoints from config + registry."""

from __future__ import annotations

from typing import Optional

from nexus.server.config import ServersConfig
from nexus.server.registry import ServerRegistry


def resolve_grpc_target(
    *,
    base_url: Optional[str] = None,
    server_ref: Optional[str] = None,
    registry: Optional[ServerRegistry] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """Return host:port for a gRPC media server."""
    if registry and server_ref:
        return registry.target_for(server_ref, tenant_id=tenant_id)
    if base_url:
        url = base_url.strip()
        for prefix in ("grpc://", "http://", "https://"):
            if url.startswith(prefix):
                url = url[len(prefix) :]
        return url.rstrip("/")
    if server_ref:
        raise ValueError(
            f"server_ref={server_ref!r} requires a ServerRegistry; "
            "pass registry= or set base_url"
        )
    raise ValueError("Media adapter requires base_url or server_ref")


def registry_from_config(config: ServersConfig) -> ServerRegistry:
    return ServerRegistry(config)
