"""Tests for session group aggregation."""

import os
import tempfile
from datetime import datetime, timedelta

import pytest

from nexus.config.storage import SessionStorageConfig
from nexus.session.adapters.file import FileStorageAdapter
from nexus.session.adapters.memory import MemoryStorageAdapter
from nexus.session.ids import member_session_id
from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, ToolCallRecord, TurnRecord


def _turn(
    index: int,
    *,
    user_message: str = "hello",
    tool_calls: list[ToolCallRecord] | None = None,
    ts: datetime | None = None,
) -> TurnRecord:
    return TurnRecord(
        turn_index=index,
        user_message=user_message,
        tool_calls=tool_calls or [],
        timestamp=ts or datetime.now(),
    )


def _delegate_tc(member: str, ts: datetime) -> ToolCallRecord:
    return ToolCallRecord(
        tc_index=0,
        tool_name=f"delegate_to_{member}",
        raw_response="done",
        timestamp=ts,
    )


async def _save(manager: SessionManager, session: AgentSession) -> None:
    existing = await manager.load_session(
        session.session_id,
        tenant_id=session.tenant_id,
        user_id=session.user_id,
    )
    if existing:
        await manager.save_session(session)
    else:
        await manager.create_session(
            agent_id=session.agent_id,
            session_id=session.session_id,
            tenant_id=session.tenant_id,
            user_id=session.user_id,
        )
        created = await manager.load_session(
            session.session_id,
            tenant_id=session.tenant_id,
            user_id=session.user_id,
        )
        created.turns = session.turns
        await manager.save_session(created)


@pytest.mark.asyncio
async def test_single_agent_session_group():
    manager = SessionManager(storage_adapter=MemoryStorageAdapter())
    root = "chat-1"
    await manager.create_session(
        agent_id="assistant", session_id=root, tenant_id="t1", user_id="u1"
    )
    sess = await manager.load_session(root, tenant_id="t1", user_id="u1")
    sess.turns.append(_turn(0, user_message="hi"))
    await manager.save_session(sess)

    view = await manager.load_session_group(
        root, tenant_id="t1", user_id="u1", pattern="single"
    )
    assert view.root_session_id == root
    assert view.pattern == "single"
    assert len(view.sessions) == 1
    assert view.sessions[0].session_id == root
    assert len(view.sessions[0].turns) == 1


@pytest.mark.asyncio
async def test_pipeline_session_group_order():
    manager = SessionManager(storage_adapter=MemoryStorageAdapter())
    root = "group-1"
    t0 = datetime(2025, 1, 1, 12, 0, 0)

    for name, offset in [("researcher", 0), ("analyst", 1)]:
        sid = member_session_id(root, name)
        session = AgentSession(
            session_id=sid,
            agent_id=name,
            tenant_id="t1",
            user_id="u1",
            turns=[_turn(0, user_message=f"work-{name}", ts=t0 + timedelta(minutes=offset))],
        )
        await _save(manager, session)

    view = await manager.load_session_group(
        root,
        tenant_id="t1",
        user_id="u1",
        pattern="pipeline",
        member_order=["researcher", "analyst"],
    )
    assert view.pattern == "pipeline"
    assert [n.member_name for n in view.sessions] == ["researcher", "analyst"]
    assert all(not n.children for n in view.sessions)


@pytest.mark.asyncio
async def test_supervisor_session_group_nested_children():
    manager = SessionManager(storage_adapter=MemoryStorageAdapter())
    root = "group-2"
    base = datetime(2025, 1, 1, 12, 0, 0)

    supervisor = AgentSession(
        session_id=member_session_id(root, "supervisor"),
        agent_id="supervisor",
        tenant_id="t1",
        user_id="u1",
        turns=[
            _turn(
                0,
                user_message="plan",
                tool_calls=[
                    _delegate_tc("researcher", base + timedelta(minutes=1)),
                    _delegate_tc("analyst", base + timedelta(minutes=5)),
                ],
                ts=base,
            )
        ],
    )
    researcher = AgentSession(
        session_id=member_session_id(root, "researcher"),
        agent_id="researcher",
        tenant_id="t1",
        user_id="u1",
        turns=[_turn(0, user_message="research", ts=base + timedelta(minutes=2))],
    )
    analyst = AgentSession(
        session_id=member_session_id(root, "analyst"),
        agent_id="analyst",
        tenant_id="t1",
        user_id="u1",
        turns=[_turn(0, user_message="analyze", ts=base + timedelta(minutes=6))],
    )

    for session in (supervisor, researcher, analyst):
        await _save(manager, session)

    view = await manager.load_session_group(
        root, tenant_id="t1", user_id="u1", pattern="supervisor"
    )
    assert view.pattern == "supervisor"
    assert len(view.sessions) == 1
    sup_node = view.sessions[0]
    assert sup_node.member_name == "supervisor"
    assert len(sup_node.children) == 2
    assert sup_node.children[0].member_name == "researcher"
    assert sup_node.children[1].member_name == "analyst"


@pytest.mark.asyncio
async def test_repeated_delegation_turn_slices():
    manager = SessionManager(storage_adapter=MemoryStorageAdapter())
    root = "group-3"
    base = datetime(2025, 1, 1, 12, 0, 0)

    supervisor = AgentSession(
        session_id=member_session_id(root, "supervisor"),
        agent_id="supervisor",
        tenant_id="t1",
        user_id="u1",
        turns=[
            _turn(
                0,
                tool_calls=[
                    _delegate_tc("researcher", base + timedelta(minutes=1)),
                    _delegate_tc("researcher", base + timedelta(minutes=5)),
                ],
                ts=base,
            )
        ],
    )
    researcher = AgentSession(
        session_id=member_session_id(root, "researcher"),
        agent_id="researcher",
        tenant_id="t1",
        user_id="u1",
        turns=[
            _turn(0, user_message="first", ts=base + timedelta(minutes=2)),
            _turn(1, user_message="second", ts=base + timedelta(minutes=6)),
        ],
    )
    await _save(manager, supervisor)
    await _save(manager, researcher)

    view = await manager.load_session_group(
        root, tenant_id="t1", user_id="u1", pattern="supervisor"
    )
    children = view.sessions[0].children
    assert len(children) == 2
    assert len(children[0].turns) == 1
    assert children[0].turns[0].user_message == "first"
    assert len(children[1].turns) == 1
    assert children[1].turns[0].user_message == "second"


@pytest.mark.asyncio
async def test_curator_session_excluded_by_default():
    manager = SessionManager(storage_adapter=MemoryStorageAdapter())
    root = "chat-4"
    curator = AgentSession(
        session_id=f"{root}__memcurator",
        agent_id="curator",
        tenant_id="t1",
        user_id="u1",
        turns=[_turn(0)],
    )
    member = AgentSession(
        session_id=member_session_id(root, "worker"),
        agent_id="worker",
        tenant_id="t1",
        user_id="u1",
        turns=[_turn(0)],
    )
    await _save(manager, curator)
    await _save(manager, member)

    view = await manager.load_session_group(root, tenant_id="t1", user_id="u1")
    assert len(view.sessions) == 1
    assert view.sessions[0].member_name == "worker"

    view_with_internal = await manager.load_session_group(
        root, tenant_id="t1", user_id="u1", include_internal=True
    )
    assert len(view_with_internal.sessions) == 2


@pytest.mark.asyncio
async def test_list_sessions_by_prefix_memory():
    manager = SessionManager(storage_adapter=MemoryStorageAdapter())
    root = "grp-5"
    for name in ("a", "b", "other"):
        sid = member_session_id(root, name) if name != "other" else "unrelated_x"
        await manager.create_session(
            agent_id=name, session_id=sid, tenant_id="t1", user_id="u1"
        )

    found = await manager.list_sessions_by_prefix(
        f"{root}_", tenant_id="t1", user_id="u1"
    )
    assert {s.session_id for s in found} == {
        member_session_id(root, "a"),
        member_session_id(root, "b"),
    }


@pytest.mark.asyncio
async def test_list_sessions_by_prefix_file_and_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_manager = SessionManager(
            storage_adapter=FileStorageAdapter(data_root=tmpdir, tenant_scoped=True)
        )
        root = "grp-6"
        for name in ("x", "y"):
            await file_manager.create_session(
                agent_id=name,
                session_id=member_session_id(root, name),
                tenant_id="t1",
                user_id="u1",
            )
        file_found = await file_manager.list_sessions_by_prefix(
            f"{root}_", tenant_id="t1", user_id="u1"
        )
        assert len(file_found) == 2

    pytest.importorskip("aiosqlite")
    with tempfile.TemporaryDirectory() as tmpdir:
        from nexus.session.adapters.sqlite import SQLiteStorageAdapter

        sqlite_manager = SessionManager(
            storage_adapter=SQLiteStorageAdapter(data_root=tmpdir, tenant_scoped=True)
        )
        root = "grp-7"
        for name in ("p", "q"):
            await sqlite_manager.create_session(
                agent_id=name,
                session_id=member_session_id(root, name),
                tenant_id="t1",
                user_id="u1",
            )
        sqlite_found = await sqlite_manager.list_sessions_by_prefix(
            f"{root}_", tenant_id="t1", user_id="u1"
        )
        assert len(sqlite_found) == 2


@pytest.mark.asyncio
async def test_postgresql_config_requires_dsn():
    with pytest.raises(ValueError, match="dsn"):
        SessionManager.from_config(
            SessionStorageConfig(adapter="postgresql", adapter_config={})
        )


@pytest.mark.asyncio
async def test_postgresql_load_session_group_integration():
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
    root = "pg-integration"
    from nexus.session.ids import member_session_id

    await manager.create_session(
        agent_id="agent", session_id=member_session_id(root, "m1")
    )
    view = await manager.load_session_group(root)
    assert view.root_session_id == root
    assert len(view.sessions) == 1
    adapter = manager._adapter
    if hasattr(adapter, "close"):
        await adapter.close()
