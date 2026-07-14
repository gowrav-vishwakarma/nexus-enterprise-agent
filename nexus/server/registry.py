"""Server endpoint registry with health checks and round-robin."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import grpc

from nexus.server.config import ModelServerSpec, ServersConfig
from nexus.server.proto import media_pb2, media_pb2_grpc

logger = logging.getLogger(__name__)


@dataclass
class ServerEndpoint:
    """Resolved endpoint for a logical server name."""

    name: str
    spec: ModelServerSpec
    channel: Optional[grpc.aio.Channel] = None
    healthy: bool = False
    _rr_index: int = 0

    @property
    def target(self) -> str:
        return self.spec.endpoint


class ServerRegistry:
    """Resolve logical server names to gRPC endpoints and track health."""

    def __init__(self, config: ServersConfig) -> None:
        self.config = config
        self._endpoints: dict[str, ServerEndpoint] = {}
        self._tenant_pools: dict[str, dict[str, str]] = {}
        for name, spec in config.servers.items():
            self._endpoints[name] = ServerEndpoint(name=name, spec=spec)

    def register_tenant_pool(self, tenant_id: str, mapping: dict[str, str]) -> None:
        """Map tenant_id -> {logical_name: server_name} for dedicated pools."""
        self._tenant_pools[tenant_id] = mapping

    def resolve(self, name: str, *, tenant_id: Optional[str] = None) -> ServerEndpoint:
        """Resolve a server ref, optionally via tenant pool."""
        if tenant_id and tenant_id in self._tenant_pools:
            mapped = self._tenant_pools[tenant_id].get(name, name)
            name = mapped
        if name not in self._endpoints:
            known = ", ".join(sorted(self._endpoints)) or "(none)"
            raise KeyError(f"Unknown server {name!r}; known: {known}")
        return self._endpoints[name]

    def target_for(self, name: str, *, tenant_id: Optional[str] = None) -> str:
        return self.resolve(name, tenant_id=tenant_id).target

    async def _get_channel(self, ep: ServerEndpoint) -> grpc.aio.Channel:
        if ep.channel is None:
            ep.channel = grpc.aio.insecure_channel(ep.target)
        return ep.channel

    async def check_health(self, name: str) -> bool:
        ep = self.resolve(name)
        try:
            channel = await self._get_channel(ep)
            stub = media_pb2_grpc.HealthServiceStub(channel)
            resp = await stub.Check(media_pb2.HealthRequest(), timeout=5.0)
            ep.healthy = resp.status == "ok"
        except Exception as exc:
            logger.warning("Health check failed for %s (%s): %s", name, ep.target, exc)
            ep.healthy = False
        return ep.healthy

    async def check_all(self, names: Optional[list[str]] = None) -> dict[str, bool]:
        targets = names or list(self._endpoints)
        results: dict[str, bool] = {}
        for name in targets:
            results[name] = await self.check_health(name)
        return results

    async def require_healthy(self, names: list[str]) -> None:
        """Fail fast if any referenced server is unhealthy."""
        results = await self.check_all(names)
        bad = [n for n, ok in results.items() if not ok]
        if bad:
            raise RuntimeError(
                f"Media server(s) not healthy: {', '.join(bad)}. "
                "Start them with: uv run python -m nexus.server up"
            )

    async def close(self) -> None:
        for ep in self._endpoints.values():
            if ep.channel is not None:
                await ep.channel.close()
                ep.channel = None

    def list_servers(self) -> list[dict]:
        return [
            {
                "name": ep.name,
                "kind": ep.spec.kind,
                "engine": ep.spec.engine,
                "endpoint": ep.target,
                "healthy": ep.healthy,
            }
            for ep in self._endpoints.values()
        ]
