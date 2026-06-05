"""Integration tests for Redis session storage (requires NEXUS_TEST_REDIS_URL)."""

import os

import pytest

from nexus.session.manager import SessionManager
from nexus.config.storage import SessionStorageConfig
from nexus.session.models import TurnRecord


@pytest.fixture
async def redis_manager():
    url = os.getenv("NEXUS_TEST_REDIS_URL")
    if not url:
        pytest.skip("NEXUS_TEST_REDIS_URL not set")
    pytest.importorskip("redis")
    manager = SessionManager.from_config(
        SessionStorageConfig(
            adapter="redis",
            adapter_config={"url": url, "key_prefix": "test:nexus:"},
        )
    )
    yield manager
    adapter = manager._adapter
    if hasattr(adapter, "close"):
        await adapter.close()


@pytest.mark.asyncio
async def test_redis_save_load(redis_manager):
    sess = await redis_manager.create_session(
        agent_id="agent-1",
        session_id="redis-sess-1",
        tenant_id="t1",
        user_id="u1",
    )
    loaded = await redis_manager.load_session("redis-sess-1")
    assert loaded is not None
    assert loaded.session_id == sess.session_id


@pytest.mark.asyncio
async def test_redis_append_turn(redis_manager):
    await redis_manager.create_session(
        agent_id="agent-1",
        session_id="redis-sess-2",
        tenant_id="t1",
        user_id="u1",
    )
    await redis_manager.append_turn(
        "redis-sess-2",
        TurnRecord(turn_index=0, user_message="hi"),
        tenant_id="t1",
        user_id="u1",
    )
    loaded = await redis_manager.load_session("redis-sess-2")
    assert loaded is not None
    assert len(loaded.turns) == 1


@pytest.mark.asyncio
async def test_redis_list_by_prefix(redis_manager):
    await redis_manager.create_session(
        agent_id="a",
        session_id="grp_x_a",
        tenant_id="t1",
        user_id="u1",
    )
    await redis_manager.create_session(
        agent_id="b",
        session_id="grp_x_b",
        tenant_id="t1",
        user_id="u1",
    )
    found = await redis_manager.list_sessions_by_prefix(
        "grp_x_", tenant_id="t1", user_id="u1"
    )
    assert len(found) == 2
