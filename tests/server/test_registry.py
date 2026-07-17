"""Tests for server registry."""

import pytest

from nexus.server.config import ModelServerSpec, ServersConfig
from nexus.server.registry import ServerRegistry


@pytest.mark.asyncio
async def test_registry_resolve_target():
    cfg = ServersConfig(
        servers={"tts_a": ModelServerSpec(kind="tts", engine="mock", port=50052)}
    )
    reg = ServerRegistry(cfg)
    assert reg.target_for("tts_a") == "127.0.0.1:50052"
    await reg.close()


@pytest.mark.asyncio
async def test_registry_tenant_pool():
    cfg = ServersConfig(
        servers={
            "shared": ModelServerSpec(kind="stt", engine="mock", port=50051),
            "vip": ModelServerSpec(kind="stt", engine="mock", port=50061),
        }
    )
    reg = ServerRegistry(cfg)
    reg.register_tenant_pool("tenant_vip", {"stt_main": "vip"})
    assert reg.target_for("stt_main", tenant_id="tenant_vip") == "127.0.0.1:50061"
    assert reg.target_for("shared", tenant_id="other") == "127.0.0.1:50051"
    await reg.close()


@pytest.mark.asyncio
async def test_registry_require_healthy_fails_without_servers():
    cfg = ServersConfig(
        servers={"down": ModelServerSpec(kind="stt", engine="mock", port=59999)}
    )
    reg = ServerRegistry(cfg)
    with pytest.raises(RuntimeError, match="not healthy"):
        await reg.require_healthy(["down"])
    await reg.close()
