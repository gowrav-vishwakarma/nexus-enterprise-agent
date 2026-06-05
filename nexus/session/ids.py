"""Session ID helpers for root/member group sessions."""

from __future__ import annotations

INTERNAL_SESSION_SUFFIX = "__memcurator"


def member_session_id(root: str, member_name: str, prefix: str = "") -> str:
    """Build a member session id from root chat id and member name."""
    return f"{prefix}{root}_{member_name}"


def group_session_prefix(root: str, prefix: str = "") -> str:
    """Prefix used to discover all member sessions for a root chat id."""
    return f"{prefix}{root}_"


def parse_member_name(
    session_id: str,
    root: str,
    prefix: str = "",
) -> str | None:
    """Extract member name from a member session id, or None if not a member."""
    expected_prefix = group_session_prefix(root, prefix)
    if not session_id.startswith(expected_prefix):
        return None
    member_name = session_id[len(expected_prefix) :]
    if not member_name or member_name.endswith(INTERNAL_SESSION_SUFFIX):
        return None
    return member_name


def is_internal_session(session_id: str, root: str, prefix: str = "") -> bool:
    """Return True for internal sub-sessions (e.g. memory curator)."""
    expected = f"{prefix}{root}{INTERNAL_SESSION_SUFFIX}"
    return session_id == expected or session_id.endswith(INTERNAL_SESSION_SUFFIX)
