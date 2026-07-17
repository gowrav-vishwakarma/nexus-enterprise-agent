"""Tests for the SQLite storage adapter."""

import os
import tempfile
from pathlib import Path

import pytest

from nexus.session.adapters.sqlite import SQLiteStorageAdapter
from nexus.session.manager import SessionManager
from nexus.session.models import ToolCallRecord, TurnRecord
from nexus.session.scope import SessionScope
from nexus.storage.paths import sessions_db_path


@pytest.mark.asyncio
async def test_sqlite_create_and_load_tenant_scoped():
    """Session survives a save→load round-trip in per-user sessions.db."""
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = SQLiteStorageAdapter(data_root=tmpdir, tenant_scoped=True)
        manager = SessionManager(storage_adapter=adapter)
        scope = SessionScope(tenant_id="t1", user_id="u1")

        sess = await manager.create_session(
            agent_id="agent-sqlite", session_id="sq-1", tenant_id="t1", user_id="u1"
        )
        db_path = sessions_db_path("t1", "u1", data_root=tmpdir)
        assert db_path.exists()

        loaded = await manager.load_session("sq-1", scope=scope)

        assert loaded is not None
        assert loaded.agent_id == "agent-sqlite"
        assert loaded.tenant_id == "t1"


@pytest.mark.asyncio
async def test_sqlite_append_turn():
    """append_turn persists tool calls correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(
            storage_adapter=SQLiteStorageAdapter(data_root=tmpdir, tenant_scoped=True)
        )
        scope = SessionScope(tenant_id="t1", user_id="u1")

        await manager.create_session(
            agent_id="agent-sqlite",
            session_id="sq-2",
            tenant_id="t1",
            user_id="u1",
        )

        tc = ToolCallRecord(tc_index=0, tool_name="calc", raw_response="42")
        turn = TurnRecord(turn_index=0, user_message="What is 6×7?", tool_calls=[tc])
        await manager.append_turn("sq-2", turn, scope=scope)

        loaded = await manager.load_session("sq-2", scope=scope)
        assert len(loaded.turns) == 1
        assert loaded.turns[0].tool_calls[0].tool_name == "calc"
        assert loaded.turns[0].tool_calls[0].raw_response == "42"


@pytest.mark.asyncio
async def test_sqlite_update_tc_summary():
    """TC summary update is persisted and flagged correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(
            storage_adapter=SQLiteStorageAdapter(data_root=tmpdir, tenant_scoped=True)
        )
        scope = SessionScope(tenant_id="t1", user_id="u1")

        await manager.create_session(
            agent_id="a", session_id="sq-3", tenant_id="t1", user_id="u1"
        )
        tc = ToolCallRecord(tc_id="TC1", tc_index=0, tool_name="search", raw_response="big output")
        await manager.append_turn(
            "sq-3",
            TurnRecord(turn_index=0, tool_calls=[tc]),
            scope=scope,
        )

        await manager.update_tc_summary(
            "sq-3", "TC1", "short summary", summarized_by_turn=1,
            scope=scope,
        )

        loaded = await manager.load_session("sq-3", scope=scope)
        updated_tc = loaded.turns[0].tool_calls[0]
        assert updated_tc.summarized_response == "short summary"
        assert updated_tc.summarized_by_turn == 1
        assert updated_tc.is_dropped is False

        await manager.update_tc_summary(
            "sq-3", "TC1", "[]", summarized_by_turn=2,
            scope=scope,
        )
        loaded = await manager.load_session("sq-3", scope=scope)
        assert loaded.turns[0].tool_calls[0].is_dropped is True


@pytest.mark.asyncio
async def test_sqlite_list_and_delete():
    """list_sessions filters and delete removes the row."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(
            storage_adapter=SQLiteStorageAdapter(data_root=tmpdir, tenant_scoped=True)
        )
        acme_scope = SessionScope(tenant_id="acme", user_id="u1")

        await manager.create_session(
            agent_id="bot", session_id="sq-4", tenant_id="acme", user_id="u1"
        )
        await manager.create_session(
            agent_id="bot", session_id="sq-5", tenant_id="acme", user_id="u1"
        )
        await manager.create_session(
            agent_id="bot", session_id="sq-6", tenant_id="other", user_id="u2"
        )

        acme_sessions = await manager.list_sessions(
            agent_id="bot", scope=acme_scope
        )
        assert len(acme_sessions) == 2
        assert all(s.tenant_id == "acme" for s in acme_sessions)

        await manager.delete_session("sq-4", scope=acme_scope)
        assert await manager.load_session("sq-4", scope=acme_scope) is None
        assert await manager.load_session("sq-5", scope=acme_scope) is not None


@pytest.mark.asyncio
async def test_sqlite_legacy_flat_db():
    """Legacy single-db mode for explicit db_path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = os.path.join(tmpdir, "test.db")
        manager = SessionManager(
            storage_adapter=SQLiteStorageAdapter(
                db_path=db, tenant_scoped=False
            )
        )
        await manager.create_session(agent_id="a", session_id="sq-legacy")
        assert Path(db).exists()
        loaded = await manager.load_session("sq-legacy")
        assert loaded is not None
