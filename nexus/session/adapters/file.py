"""File-based storage adapter."""

import asyncio
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from filelock import FileLock

from nexus.session.adapters.base import StorageAdapter
from nexus.session.models import AgentSession, TurnRecord




class FileStorageAdapter(StorageAdapter):
    """File-based JSON storage with filelock for concurrency."""
    
    def __init__(
        self,
        base_path: str = "./nexus_sessions",
        filename_template: str = "{session_id}.json",
        overwrite_mode: str = "full_rewrite",
        pretty_print: bool = False,
    ):
        self.base_path = Path(base_path)
        self.filename_template = filename_template
        self.overwrite_mode = overwrite_mode
        self.pretty_print = pretty_print
        self._locks: dict[str, FileLock] = {}
        self._io_lock = asyncio.Lock()
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def _get_path(self, session_id: str) -> Path:
        filename = self.filename_template.format(session_id=session_id)
        return self.base_path / filename
    
    def _get_lock(self, session_id: str) -> FileLock:
        if session_id not in self._locks:
            lock_path = self.base_path / f".{session_id}.lock"
            self._locks[session_id] = FileLock(str(lock_path))
        return self._locks[session_id]
    
    def _serialize_session(self, session: AgentSession) -> str:
        data = session.model_dump()
        indent = 2 if self.pretty_print else None
        return json.dumps(data, indent=indent, default=str)
    
    def _deserialize_session(self, data: str) -> AgentSession:
        parsed = json.loads(data)
        # Convert timestamp strings back to datetime
        for key in ["created_at", "updated_at"]:
            if parsed.get(key):
                parsed[key] = datetime.fromisoformat(parsed[key])
        for turn in parsed.get("turns", []):
            for key in ["timestamp"]:
                if turn.get(key):
                    turn[key] = datetime.fromisoformat(turn[key])
            for tc in turn.get("tool_calls", []):
                if tc.get("timestamp"):
                    tc["timestamp"] = datetime.fromisoformat(tc["timestamp"])
        return AgentSession(**parsed)
    
    async def save_session(self, session: AgentSession) -> None:
        path = self._get_path(session.session_id)
        lock = self._get_lock(session.session_id)
        async with self._io_lock:
            with lock:
                content = self._serialize_session(session)
                path.write_text(content)
    
    async def load_session(self, session_id: str) -> Optional[AgentSession]:
        path = self._get_path(session_id)
        lock = self._get_lock(session_id)
        async with self._io_lock:
            with lock:
                if not path.exists():
                    return None
                content = path.read_text()
                return self._deserialize_session(content)
    
    async def list_sessions(
        self,
        agent_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentSession]:
        results = []
        for path in self.base_path.glob("*.json"):
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
                if len(results) >= offset + limit:
                    break
            except Exception:
                continue
        return results[offset:]
    
    async def delete_session(self, session_id: str) -> None:
        path = self._get_path(session_id)
        lock = self._get_lock(session_id)
        async with self._io_lock:
            with lock:
                path.unlink(missing_ok=True)
    
    async def append_turn(self, session_id: str, turn: TurnRecord) -> None:
        session = await self.load_session(session_id)
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
    ) -> None:
        session = await self.load_session(session_id)
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
