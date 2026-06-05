"""Tests for storage adapters and SessionManager."""

import os
import shutil
import tempfile
import pytest

from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, TurnRecord, ToolCallRecord
from nexus.session.adapters.memory import MemoryStorageAdapter
from nexus.session.adapters.file import FileStorageAdapter
from nexus.storage.paths import session_file


@pytest.mark.asyncio
async def test_memory_storage_adapter():
    """Test memory storage adapter operations."""
    adapter = MemoryStorageAdapter(max_sessions=2)
    manager = SessionManager(storage_adapter=adapter)

    # Create session
    sess = await manager.create_session(agent_id="agent-1", session_id="sess-1")
    assert sess.session_id == "sess-1"
    assert sess.agent_id == "agent-1"

    # Load session
    loaded = await manager.load_session("sess-1")
    assert loaded is not None
    assert loaded.agent_id == "agent-1"

    # Save updates
    sess.working_memory = "New working notes"
    await manager.save_session(sess)
    loaded = await manager.load_session("sess-1")
    assert loaded.working_memory == "New working notes"

    # Append turn
    tc = ToolCallRecord(
        tc_index=1,
        tool_name="web_search",
        raw_response="Search result content",
    )
    turn = TurnRecord(
        turn_index=0,
        user_message="Hello",
        tool_calls=[tc],
        status="completed",
    )
    await manager.append_turn("sess-1", turn)
    loaded = await manager.load_session("sess-1")
    assert len(loaded.turns) == 1
    assert loaded.turns[0].user_message == "Hello"
    assert len(loaded.turns[0].tool_calls) == 1

    # Test eviction (max_sessions = 2)
    await manager.create_session(agent_id="agent-2", session_id="sess-2")
    # Eviction only happens when creating/saving new sessions that exceed capacity
    await manager.create_session(agent_id="agent-3", session_id="sess-3")
    
    # Oldest session ("sess-1") should be evicted
    assert await manager.load_session("sess-1") is None
    assert await manager.load_session("sess-2") is not None
    assert await manager.load_session("sess-3") is not None


@pytest.mark.asyncio
async def test_file_storage_adapter_tenant_scoped():
    """Test tenant-scoped file storage layout."""
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = FileStorageAdapter(data_root=tmpdir, pretty_print=True, tenant_scoped=True)
        manager = SessionManager(storage_adapter=adapter)

        sess = await manager.create_session(
            agent_id="agent-1",
            session_id="file-sess-1",
            tenant_id="t1",
            user_id="u1",
        )
        assert sess.session_id == "file-sess-1"

        expected = session_file("t1", "u1", "file-sess-1", data_root=tmpdir)
        assert expected.exists()

        loaded = await manager.load_session(
            "file-sess-1", tenant_id="t1", user_id="u1"
        )
        assert loaded is not None
        assert loaded.agent_id == "agent-1"

        tc = ToolCallRecord(
            tc_index=0,
            tool_name="run_code",
            raw_response="print('hi')",
        )
        turn = TurnRecord(
            turn_index=0,
            user_message="run this code",
            tool_calls=[tc],
        )
        await manager.append_turn(
            "file-sess-1", turn, tenant_id="t1", user_id="u1"
        )

        loaded = await manager.load_session(
            "file-sess-1", tenant_id="t1", user_id="u1"
        )
        assert len(loaded.turns) == 1
        assert loaded.turns[0].tool_calls[0].tool_name == "run_code"

        sessions = await manager.list_sessions(
            agent_id="agent-1", tenant_id="t1", user_id="u1"
        )
        assert len(sessions) == 1
        assert sessions[0].session_id == "file-sess-1"

        await manager.delete_session(
            "file-sess-1", tenant_id="t1", user_id="u1"
        )
        assert not expected.exists()
        assert await manager.load_session(
            "file-sess-1", tenant_id="t1", user_id="u1"
        ) is None


@pytest.mark.asyncio
async def test_file_storage_adapter_legacy_flat():
    """Legacy flat layout escape hatch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = FileStorageAdapter(
            base_path=tmpdir, tenant_scoped=False, pretty_print=True
        )
        manager = SessionManager(storage_adapter=adapter)

        sess = await manager.create_session(agent_id="agent-1", session_id="file-sess-1")
        file_path = os.path.join(tmpdir, "file-sess-1.json")
        assert os.path.exists(file_path)

        loaded = await manager.load_session("file-sess-1")
        assert loaded is not None
