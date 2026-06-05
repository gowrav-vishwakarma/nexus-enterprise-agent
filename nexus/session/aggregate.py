"""Session group aggregation — load and join sub-agent sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from nexus.session.group import SessionGroupView, SessionNode
from nexus.session.ids import (
    group_session_prefix,
    is_internal_session,
    parse_member_name,
)
from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, TurnRecord

PatternKind = Literal["auto", "pipeline", "supervisor", "single"]


def session_to_node(session: AgentSession, member_name: Optional[str] = None) -> SessionNode:
    """Convert an AgentSession to a SessionNode."""
    return SessionNode(
        session_id=session.session_id,
        agent_id=session.agent_id,
        member_name=member_name,
        turns=list(session.turns),
        metadata=dict(session.metadata),
        created_at=session.created_at,
        updated_at=session.updated_at,
        children=[],
    )


def _find_supervisor_name(sessions_by_member: dict[str, AgentSession]) -> Optional[str]:
    if "supervisor" in sessions_by_member:
        return "supervisor"
    for name in sessions_by_member:
        if "supervisor" in name.lower():
            return name
    return None


def _has_delegate_tools(session: AgentSession) -> bool:
    for turn in session.turns:
        for tc in turn.tool_calls:
            if tc.tool_name.startswith("delegate_to_"):
                return True
    return False


def _collect_delegate_calls(session: AgentSession) -> list[tuple[str, datetime]]:
    """Return (member_name, timestamp) for each delegate tool call in order."""
    calls: list[tuple[str, datetime]] = []
    for turn in sorted(session.turns, key=lambda t: t.turn_index):
        for tc in sorted(turn.tool_calls, key=lambda t: t.tc_index):
            if tc.tool_name.startswith("delegate_to_"):
                member = tc.tool_name[len("delegate_to_") :]
                calls.append((member, tc.timestamp))
    return calls


def _slice_turns_by_timestamp(
    turns: list[TurnRecord],
    start: datetime,
    end: Optional[datetime],
) -> list[TurnRecord]:
    sliced = []
    for turn in sorted(turns, key=lambda t: t.turn_index):
        if turn.timestamp < start:
            continue
        if end is not None and turn.timestamp >= end:
            break
        sliced.append(turn)
    return sliced


def build_pipeline_tree(
    sessions_by_member: dict[str, AgentSession],
    member_order: list[str],
) -> list[SessionNode]:
    """Build flat sibling nodes in pipeline execution order."""
    nodes: list[SessionNode] = []
    for name in member_order:
        session = sessions_by_member.get(name)
        if session is None:
            continue
        nodes.append(session_to_node(session, member_name=name))
    return nodes


def build_supervisor_tree(
    sessions_by_member: dict[str, AgentSession],
    supervisor_name: Optional[str] = None,
) -> list[SessionNode]:
    """Build supervisor node with nested delegation children in tool-call order."""
    resolved_supervisor = supervisor_name or _find_supervisor_name(sessions_by_member)
    if resolved_supervisor is None:
        return build_chronological_tree(sessions_by_member)

    supervisor_session = sessions_by_member.get(resolved_supervisor)
    if supervisor_session is None:
        return build_chronological_tree(sessions_by_member)

    supervisor_node = session_to_node(supervisor_session, member_name=resolved_supervisor)
    delegate_calls = _collect_delegate_calls(supervisor_session)

    member_turn_cursors: dict[str, int] = {
        name: 0 for name in sessions_by_member if name != resolved_supervisor
    }

    for i, (member_name, delegate_ts) in enumerate(delegate_calls):
        member_session = sessions_by_member.get(member_name)
        if member_session is None:
            continue

        next_ts = delegate_calls[i + 1][1] if i + 1 < len(delegate_calls) else None
        all_turns = sorted(member_session.turns, key=lambda t: t.turn_index)
        cursor = member_turn_cursors.get(member_name, 0)

        child_turns: list[TurnRecord] = []
        for turn in all_turns[cursor:]:
            if turn.timestamp < delegate_ts:
                continue
            if next_ts is not None and turn.timestamp >= next_ts:
                break
            child_turns.append(turn)

        if not child_turns:
            child_turns = _slice_turns_by_timestamp(all_turns[cursor:], delegate_ts, next_ts)

        member_turn_cursors[member_name] = cursor + len(child_turns)

        child = SessionNode(
            session_id=member_session.session_id,
            agent_id=member_session.agent_id,
            member_name=member_name,
            turns=child_turns,
            metadata=dict(member_session.metadata),
            created_at=member_session.created_at,
            updated_at=member_session.updated_at,
            children=[],
        )
        supervisor_node.children.append(child)

    top_level = [supervisor_node]
    referenced = {resolved_supervisor} | {m for m, _ in delegate_calls}
    for name, session in sessions_by_member.items():
        if name not in referenced:
            top_level.append(session_to_node(session, member_name=name))
    return top_level


def build_chronological_tree(
    sessions_by_member: dict[str, AgentSession],
) -> list[SessionNode]:
    """Fallback: order member sessions by first turn timestamp."""
    nodes = [
        session_to_node(session, member_name=name)
        for name, session in sessions_by_member.items()
    ]
    nodes.sort(
        key=lambda n: n.turns[0].timestamp if n.turns else n.created_at,
    )
    return nodes


def resolve_pattern(
    pattern: PatternKind,
    *,
    member_order: Optional[list[str]] = None,
    sessions_by_member: dict[str, AgentSession],
) -> Literal["single", "pipeline", "supervisor", "unknown"]:
    if pattern != "auto":
        if pattern == "single" and len(sessions_by_member) <= 1:
            return "single"
        return pattern  # type: ignore[return-value]

    if member_order and len(member_order) > 1:
        return "pipeline"

    supervisor_name = _find_supervisor_name(sessions_by_member)
    if supervisor_name:
        sup = sessions_by_member.get(supervisor_name)
        if sup and _has_delegate_tools(sup):
            return "supervisor"

    if len(sessions_by_member) <= 1:
        return "single"
    return "unknown"


async def load_session_group(
    manager: SessionManager,
    root_session_id: str,
    *,
    session_id_prefix: str = "",
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    pattern: PatternKind = "auto",
    member_order: Optional[list[str]] = None,
    include_internal: bool = False,
) -> SessionGroupView:
    """Load all sessions for a root chat id and build a nested execution view."""
    lookup = {"tenant_id": tenant_id, "user_id": user_id}
    prefix = group_session_prefix(root_session_id, session_id_prefix)

    root_session = await manager.load_session(root_session_id, **lookup)
    member_sessions = await manager.list_sessions_by_prefix(
        prefix,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    if not include_internal:
        member_sessions = [
            s
            for s in member_sessions
            if not is_internal_session(s.session_id, root_session_id, session_id_prefix)
        ]

    sessions_by_member: dict[str, AgentSession] = {}
    if root_session is not None:
        sessions_by_member["__root__"] = root_session

    for session in member_sessions:
        member_name = parse_member_name(
            session.session_id, root_session_id, session_id_prefix
        )
        if member_name:
            sessions_by_member[member_name] = session

    if not sessions_by_member:
        return SessionGroupView(
            root_session_id=root_session_id,
            session_id_prefix=session_id_prefix,
            pattern="single",
            sessions=[],
        )

    resolved = resolve_pattern(
        pattern,
        member_order=member_order,
        sessions_by_member={
            k: v for k, v in sessions_by_member.items() if k != "__root__"
        },
    )

    if resolved == "single":
        if root_session is not None and not member_sessions:
            nodes = [session_to_node(root_session)]
        elif len(sessions_by_member) == 1:
            only = next(iter(sessions_by_member.values()))
            name = next(iter(sessions_by_member))
            nodes = [session_to_node(only, member_name=None if name == "__root__" else name)]
        else:
            nodes = build_chronological_tree(
                {k: v for k, v in sessions_by_member.items() if k != "__root__"}
            )
    elif resolved == "pipeline":
        order = member_order or list(
            k for k in sessions_by_member if k != "__root__"
        )
        nodes = build_pipeline_tree(
            {k: v for k, v in sessions_by_member.items() if k != "__root__"},
            order,
        )
    elif resolved == "supervisor":
        nodes = build_supervisor_tree(
            {k: v for k, v in sessions_by_member.items() if k != "__root__"}
        )
    else:
        nodes = build_chronological_tree(
            {k: v for k, v in sessions_by_member.items() if k != "__root__"}
        )

    return SessionGroupView(
        root_session_id=root_session_id,
        session_id_prefix=session_id_prefix,
        pattern=resolved,
        sessions=nodes,
    )
