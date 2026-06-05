"""Cross-session memory integration tests for Redis."""

import os

import pytest

from nexus.config.storage import SessionStorageConfig
from nexus.persistence.factory import PersistenceFactory


@pytest.fixture
async def redis_memory_store():
    url = os.getenv("NEXUS_TEST_REDIS_URL")
    if not url:
        pytest.skip("NEXUS_TEST_REDIS_URL not set")
    pytest.importorskip("redis")
    bundle = PersistenceFactory.from_storage_config(
        SessionStorageConfig(
            adapter="redis",
            adapter_config={"url": url, "key_prefix": "test:xmem:"},
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
async def test_redis_cross_session_merge(redis_memory_store):
    record = await redis_memory_store.merge_entities(
        "t1",
        "u1",
        "assistant",
        {"theme": "dark"},
        max_entities=10,
    )
    assert record.entity_memory["theme"] == "dark"

    loaded = await redis_memory_store.load("t1", "u1", "assistant")
    assert loaded is not None
    assert loaded.entity_memory["theme"] == "dark"
