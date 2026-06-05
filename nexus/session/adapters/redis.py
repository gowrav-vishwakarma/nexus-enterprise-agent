"""Redis session storage adapter."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None  # type: ignore

from nexus.session.adapters.base import StorageAdapter
from nexus.session.adapters._serde import session_from_json, session_to_json
from nexus.session.models import AgentSession, TurnRecord
from nexus.storage.paths import normalize_tenant_id, normalize_user_id

logger = logging.getLogger(__name__)


class RedisStorageAdapter(StorageAdapter):
    """Async Redis session storage using JSON blobs and ZSET indexes."""

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        key_prefix: str = "nexus:",
        session_key_template: Optional[str] = None,
        index_key_template: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        max_connections: int = 50,
        client: Any = None,
    ) -> None:
        if aioredis is None:
            raise ImportError(
                "redis is required for RedisStorageAdapter. "
                "Install with: pip install nexus-agent[redis]"
            )
        self.key_prefix = key_prefix
        self.session_key_template = session_key_template or "{prefix}session:{session_id}"
        self.index_key_template = index_key_template or "{prefix}idx:{tenant}:{user}"
        self.ttl_seconds = ttl_seconds
        self._client = client
        self._owns_client = client is None
        if client is not None:
            self._redis = client
        elif url:
            self._redis = aioredis.from_url(
                url, max_connections=max_connections, decode_responses=True
            )
        else:
            self._redis = aioredis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                max_connections=max_connections,
                decode_responses=True,
            )

    async def close(self) -> None:
        if self._owns_client and self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    def _session_key(self, session_id: str) -> str:
        return self.session_key_template.format(
            prefix=self.key_prefix,
            session_id=session_id,
        )

    def _index_key(self, tenant_id: Optional[str], user_id: Optional[str]) -> str:
        tenant = normalize_tenant_id(tenant_id)
        user = normalize_user_id(user_id)
        return self.index_key_template.format(
            prefix=self.key_prefix,
            tenant=tenant,
            user=user,
        )

    async def _apply_ttl(self, *keys: str) -> None:
        if self.ttl_seconds:
            for key in keys:
                await self._redis.expire(key, self.ttl_seconds)

    async def save_session(self, session: AgentSession) -> None:
        key = self._session_key(session.session_id)
        payload = session_to_json(session)
        await self._redis.set(key, payload)
        idx = self._index_key(session.tenant_id, session.user_id)
        score = session.created_at.timestamp()
        await self._redis.zadd(idx, {session.session_id: score})
        await self._apply_ttl(key, idx)

    async def load_session(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[AgentSession]:
        raw = await self._redis.get(self._session_key(session_id))
        if raw is None:
            return None
        session = session_from_json(raw)
        if tenant_id and session.tenant_id != tenant_id:
            return None
        if user_id and session.user_id != user_id:
            return None
        return session

    async def list_sessions(
        self,
        agent_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentSession]:
        if tenant_id is None or user_id is None:
            return await self._scan_list(agent_id, tenant_id, user_id, limit, offset)
        idx = self._index_key(tenant_id, user_id)
        ids = await self._redis.zrevrange(idx, offset, offset + limit - 1)
        sessions: list[AgentSession] = []
        for sid in ids:
            session = await self.load_session(sid, tenant_id=tenant_id, user_id=user_id)
            if session is None:
                continue
            if agent_id and session.agent_id != agent_id:
                continue
            sessions.append(session)
        return sessions

    async def _scan_list(
        self,
        agent_id: Optional[str],
        tenant_id: Optional[str],
        user_id: Optional[str],
        limit: int,
        offset: int,
    ) -> list[AgentSession]:
        pattern = self.session_key_template.format(
            prefix=self.key_prefix, session_id="*"
        )
        results: list[AgentSession] = []
        async for key in self._redis.scan_iter(match=pattern, count=200):
            raw = await self._redis.get(key)
            if not raw:
                continue
            session = session_from_json(raw)
            if agent_id and session.agent_id != agent_id:
                continue
            if tenant_id and session.tenant_id != tenant_id:
                continue
            if user_id and session.user_id != user_id:
                continue
            results.append(session)
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
        if tenant_id is not None and user_id is not None:
            idx = self._index_key(tenant_id, user_id)
            ids = await self._redis.zrange(idx, 0, -1)
            sessions: list[AgentSession] = []
            for sid in ids:
                if not sid.startswith(session_id_prefix) or sid in excluded:
                    continue
                session = await self.load_session(sid, tenant_id=tenant_id, user_id=user_id)
                if session:
                    sessions.append(session)
            sessions.sort(key=lambda s: s.created_at)
            return sessions

        pattern = f"{self.key_prefix}session:{session_id_prefix}*"
        sessions = []
        async for key in self._redis.scan_iter(match=pattern, count=200):
            sid = key.split(":")[-1] if ":" in key else key
            if sid in excluded:
                continue
            session = await self.load_session(sid, tenant_id=tenant_id, user_id=user_id)
            if session:
                sessions.append(session)
        sessions.sort(key=lambda s: s.created_at)
        return sessions

    async def delete_session(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        session = await self.load_session(session_id, tenant_id=tenant_id, user_id=user_id)
        await self._redis.delete(self._session_key(session_id))
        if session:
            idx = self._index_key(session.tenant_id, session.user_id)
            await self._redis.zrem(idx, session_id)

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
        if session is None:
            logger.warning("append_turn: session %s not found in redis", session_id)
            return
        session.turns.append(turn)
        session.updated_at = datetime.now()
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
        if session is None:
            return
        for turn in session.turns:
            for tc in turn.tool_calls:
                if tc.tc_id == tc_id:
                    tc.summarized_response = summarized_response
                    tc.summarized_by_turn = summarized_by_turn
                    if summarized_response == "[]":
                        tc.is_dropped = True
                    break
        session.updated_at = datetime.now()
        await self.save_session(session)
