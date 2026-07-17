"""In-memory AITalkChats-style adapter for tests and thin product wrappers.

Mirrors Ankpal's ``ankpal."AiTalkChats"`` layout conceptually:
- composite identity: (tenant_id, session_id) with company_id filter
- JSON blob column ``chatJson``
- side columns: company_id, user_id, user_name

Uses BaseSQLStorageAdapter's lock/mutate pattern against an in-memory map so
unit tests can exercise the custom-schema path without Postgres.
"""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime
from typing import Any, Optional

from nexus.session.adapters.base_sql import BaseSQLStorageAdapter
from nexus.session.codec import SessionCodec
from nexus.session.models import AgentSession
from nexus.session.scope import SessionScope


class _MemTx:
    def __init__(self, adapter: "AiTalkChatsMemoryAdapter"):
        self._adapter = adapter

    async def fetch_one(self, sql: str, params: list[Any]) -> Optional[dict[str, Any]]:
        # BaseSQL builds SELECT ... WHERE id = %s [AND scope] FOR UPDATE
        session_id = params[0]
        row = self._adapter._rows.get(session_id)
        if row is None:
            return None
        session = self._adapter._decode(row["chatJson"])
        scope = self._adapter._last_scope
        if scope and not scope.matches_session(session):
            return None
        return {"chatJson": row["chatJson"]}

    async def execute(self, sql: str, params: list[Any]) -> None:
        # UPDATE ... SET cols WHERE id = %s  — last param is session_id
        session_id = params[-1]
        # Rebuild from codec blob which is always the chatJson param position
        # BaseSQL writes: row_columns values then json then session_id
        # Simpler path: decode from the json param (second-to-last before id when
        # only chatJson changes). We store by re-reading from params via known layout.
        # row_columns order: tenantId, chatId, companyId, userId, userName, chatJson
        chat_json = params[-2]
        self._adapter._rows[session_id] = {
            "tenantId": params[0],
            "chatId": params[1],
            "companyId": params[2],
            "userId": params[3],
            "userName": params[4],
            "chatJson": chat_json if isinstance(chat_json, dict) else chat_json,
            "updatedAt": datetime.now(),
        }


class AiTalkChatsMemoryAdapter(BaseSQLStorageAdapter):
    """AITalk-shaped session store backed by a dict (for tests / demos)."""

    def __init__(self, *, codec: Optional[SessionCodec] = None):
        super().__init__(codec=codec)
        self._rows: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._last_scope: Optional[SessionScope] = None

    def table(self) -> str:
        return 'ankpal."AiTalkChats"'

    def json_column(self) -> str:
        return "chatJson"

    def id_column(self) -> str:
        return "chatId"

    def row_columns(self, session: AgentSession) -> dict[str, Any]:
        return {
            "tenantId": session.tenant_id,
            "chatId": session.session_id,
            "companyId": session.company_id,
            "userId": session.user_id,
            "userName": session.user_name,
        }

    def scope_where(
        self, scope: Optional[SessionScope]
    ) -> tuple[str, list[Any]]:
        self._last_scope = scope
        if scope is None:
            return "", []
        clauses: list[str] = []
        params: list[Any] = []
        if scope.tenant_id is not None:
            clauses.append('"tenantId" = %s')
            params.append(scope.tenant_id)
        if scope.company_id is not None:
            clauses.append('"companyId" = %s')
            params.append(scope.company_id)
        if scope.user_id is not None:
            clauses.append('"userId" = %s')
            params.append(scope.user_id)
        return " AND ".join(clauses), params

    def _json_param(self, session: AgentSession) -> Any:
        return self._encode(session)

    async def _fetch_one(
        self, sql: str, params: list[Any]
    ) -> Optional[dict[str, Any]]:
        session_id = params[0]
        row = self._rows.get(session_id)
        if row is None:
            return None
        session = self._decode(row["chatJson"])
        # Re-check scope against side columns
        scope = SessionScope(
            tenant_id=None,
            company_id=None,
            user_id=None,
        )
        # Parse scope from remaining params via last scope_where call
        if self._last_scope and not self._last_scope.matches_session(session):
            return None
        # Also check side columns for company
        if self._last_scope:
            if (
                self._last_scope.tenant_id is not None
                and row.get("tenantId") != self._last_scope.tenant_id
            ):
                return None
            if (
                self._last_scope.company_id is not None
                and str(row.get("companyId")) != str(self._last_scope.company_id)
            ):
                return None
        return {"chatJson": copy.deepcopy(row["chatJson"])}

    async def _fetch_all(
        self, sql: str, params: list[Any]
    ) -> list[dict[str, Any]]:
        results = []
        for row in self._rows.values():
            results.append({"chatJson": copy.deepcopy(row["chatJson"])})
        return results

    async def _execute(self, sql: str, params: list[Any]) -> None:
        # INSERT path from save_session: tenantId, chatId, companyId, userId, userName, chatJson
        if sql.strip().upper().startswith("INSERT"):
            tenant_id, chat_id, company_id, user_id, user_name, chat_json = params
            self._rows[chat_id] = {
                "tenantId": tenant_id,
                "chatId": chat_id,
                "companyId": company_id,
                "userId": user_id,
                "userName": user_name,
                "chatJson": chat_json,
                "updatedAt": datetime.now(),
            }
            return
        if sql.strip().upper().startswith("DELETE"):
            session_id = params[0]
            row = self._rows.get(session_id)
            if row is None:
                return
            if self._last_scope:
                session = self._decode(row["chatJson"])
                if not self._last_scope.matches_session(session):
                    return
            self._rows.pop(session_id, None)

    async def _execute_in_transaction(self, work) -> Any:
        async with self._lock:
            return await work(_MemTx(self))

    async def save_session(self, session: AgentSession) -> None:
        """Upsert using AITalk composite key semantics (tenantId + chatId)."""
        session.update_timestamp()
        self._rows[session.session_id] = {
            "tenantId": session.tenant_id,
            "chatId": session.session_id,
            "companyId": session.company_id,
            "userId": session.user_id,
            "userName": session.user_name,
            "chatJson": self._encode(session),
            "updatedAt": session.updated_at,
        }
