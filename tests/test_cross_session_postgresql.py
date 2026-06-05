"""Cross-session memory integration tests for PostgreSQL."""

import os

import pytest

from nexus.config.storage import SessionStorageConfig
from nexus.persistence.factory import PersistenceFactory


@pytest.fixture
async def pg_memory_store():
    dsn = os.getenv("NEXUS_TEST_PG_DSN")
    if not dsn:
        pytest.skip("NEXUS_TEST_PG_DSN not set")
    pytest.importorskip("asyncpg")
    bundle = PersistenceFactory.from_storage_config(
        SessionStorageConfig(
            adapter="postgresql",
            adapter_config={
                "dsn": dsn,
                "schema": os.getenv("NEXUS_TEST_PG_SCHEMA", "public"),
                "auto_migrate": True,
                "schema_mode": "managed",
            },
        )
    )
    store = bundle.cross_session_memory_store
    yield store
    adapter = bundle.session_manager._adapter
    if hasattr(adapter, "close"):
        await adapter.close()
    if hasattr(store, "close"):
        await store.close()


@pytest.mark.asyncio
async def test_pg_cross_session_merge(pg_memory_store):
    record = await pg_memory_store.merge_entities(
        "t1",
        "u1",
        "assistant",
        {"company": "Acme"},
        max_entities=10,
    )
    assert record.entity_memory["company"] == "Acme"

    loaded = await pg_memory_store.load("t1", "u1", "assistant")
    assert loaded is not None
    assert loaded.entity_memory["company"] == "Acme"

    updated = await pg_memory_store.merge_entities(
        "t1",
        "u1",
        "assistant",
        {"role": "CTO"},
        max_entities=10,
    )
    assert updated.entity_memory["role"] == "CTO"
    assert updated.entity_memory["company"] == "Acme"
