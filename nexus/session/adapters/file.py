"""File-based storage adapter."""

import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from filelock import FileLock

from nexus.session.adapters.base import StorageAdapter
from nexus.session.adapters._serde import session_from_json, session_to_json
from nexus.session.models import AgentSession, TurnRecord
from nexus.storage.paths import (
    get_data_root,
    lookup_session,
    normalize_tenant_id,
    register_session,
    session_file,
    session_lock_file,
    tenant_user_dir,
    unregister_session,
)


class FileStorageAdapter(StorageAdapter):
    """File-based JSON storage with filelock for concurrency."""

    def __init__(
        self,
        data_root: Optional[str] = None,
        base_path: Optional[str] = None,
        filename_template: str = "{session_id}.json",
        overwrite_mode: str = "full_rewrite",
        pretty_print: bool = False,
        tenant_scoped: bool = True,
    ):
        self.tenant_scoped = tenant_scoped
        if tenant_scoped:
            self.data_root = Path(data_root) if data_root else get_data_root()
            self.base_path = None
            self.filename_template = "session.json"
        else:
            # Legacy flat layout escape hatch
            legacy = base_path or "./nexus_sessions"
            self.base_path = Path(legacy)
            self.data_root = None
            self.filename_template = filename_template
        self.overwrite_mode = overwrite_mode
        self.pretty_print = pretty_print
        self._locks: dict[str, FileLock] = {}
        self._io_lock = asyncio.Lock()
        if self.base_path is not None:
            self.base_path.mkdir(parents=True, exist_ok=True)

    async def _resolve_location(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session: Optional[AgentSession] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        tid = tenant_id or (session.tenant_id if session else None)
        uid = user_id or (session.user_id if session else None)
        if tid is not None and uid is not None:
            return tid, uid
        if self.tenant_scoped:
            entry = await lookup_session(session_id, data_root=self.data_root)
            if entry:
                return entry.get("tenant_id"), entry.get("user_id")
        return tid, uid

    def _legacy_path(self, session_id: str) -> Path:
        filename = self.filename_template.format(session_id=session_id)
        return self.base_path / filename  # type: ignore[operator]

    def _legacy_lock_path(self, session_id: str) -> Path:
        return self.base_path / f".{session_id}.lock"  # type: ignore[operator]

    def _get_path(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
        session_id: str,
    ) -> Path:
        if self.tenant_scoped:
            return session_file(tenant_id, user_id, session_id, data_root=self.data_root)
        return self._legacy_path(session_id)

    def _get_lock_path(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
        session_id: str,
    ) -> Path:
        if self.tenant_scoped:
            return session_lock_file(tenant_id, user_id, session_id, data_root=self.data_root)
        return self._legacy_lock_path(session_id)

    def _get_lock(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
        session_id: str,
    ) -> FileLock:
        key = f"{tenant_id}:{user_id}:{session_id}"
        if key not in self._locks:
            lock_path = self._get_lock_path(tenant_id, user_id, session_id)
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._locks[key] = FileLock(str(lock_path))
        return self._locks[key]

    def _serialize_session(self, session: AgentSession) -> str:
        return session_to_json(session, pretty=self.pretty_print)

    def _deserialize_session(self, data: str) -> AgentSession:
        return session_from_json(data)

    async def save_session(self, session: AgentSession) -> None:
        tid, uid = await self._resolve_location(session.session_id, session=session)
        path = self._get_path(tid, uid, session.session_id)
        lock = self._get_lock(tid, uid, session.session_id)
        async with self._io_lock:
            with lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self._serialize_session(session))
        if self.tenant_scoped:
            await register_session(
                session.session_id, tid, uid, data_root=self.data_root
            )

    async def load_session(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[AgentSession]:
        tid, uid = await self._resolve_location(
            session_id, tenant_id=tenant_id, user_id=user_id
        )
        path = self._get_path(tid, uid, session_id)
        lock = self._get_lock(tid, uid, session_id)
        async with self._io_lock:
            with lock:
                if not path.exists():
                    if self.tenant_scoped and tenant_id is None and user_id is None:
                        return await self._scan_for_session(session_id)
                    return None
                content = path.read_text()
                return self._deserialize_session(content)

    async def _scan_for_session(self, session_id: str) -> Optional[AgentSession]:
        """Last-resort scan when index and hints are unavailable."""
        root = self.data_root
        if root is None or not root.exists():
            return None
        for path in root.rglob("session.json"):
            try:
                session = self._deserialize_session(path.read_text())
                if session.session_id == session_id:
                    await register_session(
                        session_id,
                        session.tenant_id,
                        session.user_id,
                        data_root=self.data_root,
                    )
                    return session
            except Exception:
                continue
        return None

    def _iter_session_files(
        self,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        if not self.tenant_scoped:
            yield from self.base_path.glob("*.json")  # type: ignore[union-attr]
            return

        root = self.data_root
        if tenant_id is not None and user_id is not None:
            user_dir = tenant_user_dir(tenant_id, user_id, data_root=root)
            if user_dir.exists():
                for session_path in user_dir.iterdir():
                    candidate = session_path / "session.json"
                    if candidate.is_file():
                        yield candidate
            return

        if tenant_id is not None:
            tenant_dir = root / normalize_tenant_id(tenant_id) / "users"
            if tenant_dir.exists():
                for user_dir in tenant_dir.iterdir():
                    if not user_dir.is_dir():
                        continue
                    for session_path in user_dir.iterdir():
                        candidate = session_path / "session.json"
                        if candidate.is_file():
                            yield candidate
            return

        if root.exists():
            for path in root.rglob("session.json"):
                if "_index" not in path.parts:
                    yield path

    async def list_sessions(
        self,
        agent_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentSession]:
        results = []
        for path in self._iter_session_files(tenant_id, user_id):
            try:
                content = path.read_text()
                session = self._deserialize_session(content)
                if agent_id and session.agent_id != agent_id:
                    continue
                if tenant_id and session.tenant_id != tenant_id:
                    continue
                if user_id and session.user_id != user_id:
                    continue
                results.append(session)
            except Exception:
                continue
        results.sort(key=lambda s: s.updated_at, reverse=True)
        return results[offset : offset + limit]

    async def list_sessions_by_prefix(
        self,
        session_id_prefix: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        exclude_session_ids: Optional[set[str]] = None,
    ) -> list[AgentSession]:
        excluded = exclude_session_ids or set()
        results = []
        for path in self._iter_session_files(tenant_id, user_id):
            try:
                session = self._deserialize_session(path.read_text())
                if not session.session_id.startswith(session_id_prefix):
                    continue
                if session.session_id in excluded:
                    continue
                if tenant_id and session.tenant_id != tenant_id:
                    continue
                if user_id and session.user_id != user_id:
                    continue
                results.append(session)
            except Exception:
                continue
        results.sort(key=lambda s: s.created_at)
        return results

    async def delete_session(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        tid, uid = await self._resolve_location(
            session_id, tenant_id=tenant_id, user_id=user_id
        )
        path = self._get_path(tid, uid, session_id)
        lock = self._get_lock(tid, uid, session_id)
        async with self._io_lock:
            with lock:
                if self.tenant_scoped and path.parent.is_dir():
                    shutil.rmtree(path.parent, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
        if self.tenant_scoped:
            await unregister_session(session_id, data_root=self.data_root)

    async def append_turn(
        self,
        session_id: str,
        turn: TurnRecord,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        session = await self.load_session(
            session_id, tenant_id=tenant_id, user_id=user_id
        )
        if session:
            session.turns.append(turn)
            session.update_timestamp()
            await self.save_session(session)

    async def update_tc_summary(
        self,
        session_id: str,
        tc_id: str,
        summarized_response: str,
        summarized_by_turn: int,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        session = await self.load_session(
            session_id, tenant_id=tenant_id, user_id=user_id
        )
        if session:
            for turn in session.turns:
                for tc in turn.tool_calls:
                    if tc.tc_id == tc_id:
                        tc.summarized_response = summarized_response
                        tc.summarized_by_turn = summarized_by_turn
                        if summarized_response == "[]":
                            tc.is_dropped = True
                        session.update_timestamp()
                        await self.save_session(session)
                        return
