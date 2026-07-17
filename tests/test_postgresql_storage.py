"""Integration tests for PostgreSQL session storage (requires NEXUS_TEST_PG_DSN)."""

import os

import pytest

from nexus.config.storage import SessionStorageConfig
from nexus.session.manager import SessionManager
from nexus.session.models import TurnRecord, ToolCallRecord
from nexus.session.scope import SessionScope


@pytest.fixture
async def pg_manager():
    dsn = os.getenv("NEXUS_TEST_PG_DSN")
    if not dsn:
        pytest.skip("NEXUS_TEST_PG_DSN not set")
    pytest.importorskip("asyncpg")
    manager = SessionManager.from_config(
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
    yield manager
    adapter = manager._adapter
    if hasattr(adapter, "close"):
        await adapter.close()


@pytest.mark.asyncio
async def test_pg_save_load(pg_manager):
    sess = await pg_manager.create_session(
        agent_id="agent-1",
        session_id="pg-sess-1",
        tenant_id="t1",
        user_id="u1",
    )
    loaded = await pg_manager.load_session("pg-sess-1")
    assert loaded is not None
    assert loaded.session_id == sess.session_id


@pytest.mark.asyncio
async def test_pg_append_and_update_tc(pg_manager):
    await pg_manager.create_session(
        agent_id="agent-1",
        session_id="pg-sess-2",
        tenant_id="t1",
        user_id="u1",
    )
    tc = ToolCallRecord(tc_index=0, tool_name="search", raw_response="data")
    await pg_manager.append_turn(
        "pg-sess-2",
        TurnRecord(turn_index=0, tool_calls=[tc]),
    )
    await pg_manager.update_tc_summary("pg-sess-2", tc.tc_id, "summary", 0)
    loaded = await pg_manager.load_session("pg-sess-2")
    assert loaded is not None
    assert loaded.turns[0].tool_calls[0].summarized_response == "summary"


@pytest.mark.asyncio
async def test_pg_list_by_prefix(pg_manager):
    await pg_manager.create_session(agent_id="a", session_id="pre_a", tenant_id="t1", user_id="u1")
    await pg_manager.create_session(agent_id="b", session_id="pre_b", tenant_id="t1", user_id="u1")
    found = await pg_manager.list_sessions_by_prefix(
        "pre_", scope=SessionScope(tenant_id="t1", user_id="u1")
    )
    assert len(found) >= 2
