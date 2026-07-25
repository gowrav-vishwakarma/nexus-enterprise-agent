"""RunContext — request-scoped identity, flags, and service registry."""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

if TYPE_CHECKING:
    from nexus.session.scope import SessionScope


class RunContext(BaseModel):
    """Per-request context injected into tools, stores, and storage.

    Identity fields identify the tenant / company / user. Flags control
    persistence and side effects. ``metadata`` is a plain bag for app data.
    Services (DB pools, HTTP clients) live in a private registry and are
    never serialized.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tenant_id: Optional[str] = None
    company_id: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    channel: str = "web"
    branch_id: Optional[str] = None
    auth: dict[str, Any] = Field(default_factory=dict)
    is_cron: bool = False
    is_subagent: bool = False
    persistable: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(
        default_factory=dict,
        description="Durable checkpoint state for this chat thread (synced to session when persisting).",
    )

    _services: dict[str, Any] = PrivateAttr(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Read a value from metadata."""
        return self.metadata.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Write a value into metadata."""
        self.metadata[key] = value

    def get_state(self, key: str, default: Any = None) -> Any:
        """Read a value from durable session state."""
        return self.state.get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        """Write a value into durable session state."""
        self.state[key] = value

    def service(self, key: str, default: Any = None) -> Any:
        """Look up a registered service (DB pool, client, …)."""
        return self._services.get(key, default)

    def with_service(self, key: str, value: Any) -> "RunContext":
        """Register a service and return self for chaining."""
        self._services[key] = value
        return self

    def bind_services(self, **services: Any) -> "RunContext":
        """Register many services at once."""
        self._services.update(services)
        return self

    def derive_child(
        self,
        *,
        session_id: Optional[str] = None,
        is_subagent: bool = True,
        include_context: bool = True,
    ) -> "RunContext":
        """Build a context for a nested agent run (sub-agent or sub-group)."""
        child = RunContext(
            tenant_id=self.tenant_id,
            company_id=self.company_id,
            user_id=self.user_id,
            user_name=self.user_name,
            session_id=session_id,
            request_id=self.request_id,
            channel=self.channel,
            branch_id=self.branch_id,
            auth=dict(self.auth),
            is_cron=self.is_cron,
            is_subagent=is_subagent,
            persistable=self.persistable,
            metadata=dict(self.metadata) if include_context else {},
            state=dict(self.state) if include_context else {},
        )
        child.bind_services(**self._services)
        return child

    def to_scope(self) -> "SessionScope":
        """Build a SessionScope from identity fields."""
        from nexus.session.scope import SessionScope

        return SessionScope(
            tenant_id=self.tenant_id,
            company_id=self.company_id,
            user_id=self.user_id,
        )

    @property
    def should_persist(self) -> bool:
        """False for cron / subagent / explicitly non-persistable runs."""
        if not self.persistable:
            return False
        if self.is_cron or self.is_subagent:
            return False
        return True
