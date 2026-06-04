"""Tests for the SQLite storage adapter."""

import os
import tempfile

import pytest

from nexus.session.adapters.sqlite import SQLiteStorageAdapter
from nexus.session.manager import SessionManager
from nexus.session.models import ToolCallRecord, TurnRecord


@pytest.mark.asyncio
async def test_sqlite_create_and_load():
    """Session survives a save→load round-trip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = os.path.join(tmpdir, "test.db")
        adapter = SQLiteStorageAdapter(db_path=db)
        manager = SessionManager(storage_adapter=adapter)

        sess = await manager.create_session(
            agent_id="agent-sqlite", session_id="sq-1", tenant_id="t1"
        )
        loaded = await manager.load_session("sq-1")

        assert loaded is not None
        assert loaded.agent_id == "agent-sqlite"
        assert loaded.tenant_id == "t1"


@pytest.mark.asyncio
async def test_sqlite_append_turn():
    """append_turn persists tool calls correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = os.path.join(tmpdir, "test.db")
        manager = SessionManager(storage_adapter=SQLiteStorageAdapter(db_path=db))

        await manager.create_session(agent_id="agent-sqlite", session_id="sq-2")

        tc = ToolCallRecord(tc_index=0, tool_name="calc", raw_response="42")
        turn = TurnRecord(turn_index=0, user_message="What is 6×7?", tool_calls=[tc])
        await manager.append_turn("sq-2", turn)

        loaded = await manager.load_session("sq-2")
        assert len(loaded.turns) == 1
        assert loaded.turns[0].tool_calls[0].tool_name == "calc"
        assert loaded.turns[0].tool_calls[0].raw_response == "42"


@pytest.mark.asyncio
async def test_sqlite_update_tc_summary():
    """TC summary update is persisted and flagged correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = os.path.join(tmpdir, "test.db")
        manager = SessionManager(storage_adapter=SQLiteStorageAdapter(db_path=db))

        await manager.create_session(agent_id="a", session_id="sq-3")
        tc = ToolCallRecord(tc_id="TC1", tc_index=0, tool_name="search", raw_response="big output")
        await manager.append_turn("sq-3", TurnRecord(turn_index=0, tool_calls=[tc]))

        await manager.update_tc_summary("sq-3", "TC1", "short summary", summarized_by_turn=1)

        loaded = await manager.load_session("sq-3")
        updated_tc = loaded.turns[0].tool_calls[0]
        assert updated_tc.summarized_response == "short summary"
        assert updated_tc.summarized_by_turn == 1
        assert updated_tc.is_dropped is False

        # Dropped sentinel
        await manager.update_tc_summary("sq-3", "TC1", "[]", summarized_by_turn=2)
        loaded = await manager.load_session("sq-3")
        assert loaded.turns[0].tool_calls[0].is_dropped is True


@pytest.mark.asyncio
async def test_sqlite_list_and_delete():
    """list_sessions filters and delete removes the row."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = os.path.join(tmpdir, "test.db")
        manager = SessionManager(storage_adapter=SQLiteStorageAdapter(db_path=db))

        await manager.create_session(agent_id="bot", session_id="sq-4", tenant_id="acme")
        await manager.create_session(agent_id="bot", session_id="sq-5", tenant_id="acme")
        await manager.create_session(agent_id="bot", session_id="sq-6", tenant_id="other")

        acme_sessions = await manager.list_sessions(agent_id="bot", tenant_id="acme")
        assert len(acme_sessions) == 2
        assert all(s.tenant_id == "acme" for s in acme_sessions)

        await manager.delete_session("sq-4")
        assert await manager.load_session("sq-4") is None
        assert await manager.load_session("sq-5") is not None
