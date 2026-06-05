"""Tests for tenant-scoped storage path helpers."""

import os
import tempfile

import pytest

from nexus.storage.paths import (
    get_data_root,
    lookup_session,
    memory_db_path,
    register_session,
    sanitize_segment,
    session_file,
    sessions_db_path,
    tenant_user_dir,
    unregister_session,
)


def test_sanitize_segment_replaces_unsafe_chars():
    assert sanitize_segment("acme/corp", fallback="_default") == "acme_corp"
    assert sanitize_segment(None, fallback="_default") == "_default"
    assert sanitize_segment("", fallback="_default") == "_default"


def test_tenant_user_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = tenant_user_dir("t1", "u1", data_root=tmpdir)
        assert str(root).endswith("t1/users/u1")
        assert str(session_file("t1", "u1", "sess-1", data_root=tmpdir)).endswith(
            "t1/users/u1/sess-1/session.json"
        )
        assert str(sessions_db_path("t1", "u1", data_root=tmpdir)).endswith(
            "t1/users/u1/sessions.db"
        )
        assert str(memory_db_path("t1", "u1", data_root=tmpdir)).endswith(
            "t1/users/u1/memory.db"
        )


def test_nexus_data_root_env_override(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("NEXUS_DATA_ROOT", tmpdir)
        assert str(get_data_root()) == tmpdir


@pytest.mark.asyncio
async def test_session_index_round_trip():
    with tempfile.TemporaryDirectory() as tmpdir:
        await register_session("sess-a", "t1", "u1", data_root=tmpdir)
        entry = await lookup_session("sess-a", data_root=tmpdir)
        assert entry == {"tenant_id": "t1", "user_id": "u1"}

        await unregister_session("sess-a", data_root=tmpdir)
        assert await lookup_session("sess-a", data_root=tmpdir) is None
