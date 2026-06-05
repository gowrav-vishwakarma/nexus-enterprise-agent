"""Tests for PersistenceFactory and resolver."""

import pytest

from nexus.config.storage import SessionStorageConfig
from nexus.persistence.factory import PersistenceFactory
from nexus.persistence.resolver import PersistenceResolver


class _StaticResolver:
    def resolve_storage_config(self, tenant_id, user_id):
        return SessionStorageConfig(
            adapter="memory",
            adapter_config={"max_sessions": 100},
        )

    def resolve_bundle(self, tenant_id, user_id):
        return None


class _PerTenantResolver:
    def resolve_storage_config(self, tenant_id, user_id):
        if tenant_id == "tenant-a":
            return SessionStorageConfig(
                adapter="memory",
                adapter_config={"max_sessions": 10},
            )
        return SessionStorageConfig(
            adapter="memory",
            adapter_config={"max_sessions": 20},
        )

    def resolve_bundle(self, tenant_id, user_id):
        return None


@pytest.mark.asyncio
async def test_from_storage_config_memory():
    bundle = PersistenceFactory.from_storage_config(
        SessionStorageConfig(adapter="memory")
    )
    session = await bundle.session_manager.create_session(agent_id="a1")
    assert session.agent_id == "a1"
    record = await bundle.cross_session_memory_store.merge_entities(
        "t1", "u1", "ns", {"k": "v"}, max_entities=10
    )
    assert record.entity_memory["k"] == "v"


@pytest.mark.asyncio
async def test_from_resolver():
    bundle = PersistenceFactory.from_resolver(_StaticResolver(), "t1", "u1")
    session = await bundle.session_manager.create_session(agent_id="a1")
    assert session is not None


def test_per_tenant_resolver_config():
    resolver = _PerTenantResolver()
    cfg_a = resolver.resolve_storage_config("tenant-a", "u1")
    cfg_b = resolver.resolve_storage_config("tenant-b", "u1")
    assert cfg_a.adapter_config["max_sessions"] == 10
    assert cfg_b.adapter_config["max_sessions"] == 20


def test_resolver_is_protocol():
    assert isinstance(_StaticResolver(), PersistenceResolver)
