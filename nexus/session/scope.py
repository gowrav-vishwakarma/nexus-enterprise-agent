"""SessionScope — tenant / company / user partition for storage and stores."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SessionScope(BaseModel):
    """Who owns a session, memory row, or skill.

    Built from ``RunContext.to_scope()``. Adapters and stores filter on these
    fields. Empty fields mean "do not filter on this dimension".
    """

    tenant_id: Optional[str] = Field(default=None, description="Customer / org id")
    company_id: Optional[str] = Field(
        default=None,
        description="Company within a tenant (multi-company products)",
    )
    user_id: Optional[str] = Field(default=None, description="End-user id")

    def matches_session(self, session: Any) -> bool:
        """True if a session object matches this scope's non-None fields."""
        if self.tenant_id is not None and getattr(session, "tenant_id", None) != self.tenant_id:
            return False
        if self.company_id is not None and getattr(session, "company_id", None) != self.company_id:
            return False
        if self.user_id is not None and getattr(session, "user_id", None) != self.user_id:
            return False
        return True

    def path_segments(self, *, keys: Optional[list[str]] = None) -> list[str]:
        """Folder-safe path segments for file-backed stores.

        ``keys`` selects which fields to include (in order). Default uses all
        non-None fields in tenant → company → user order.
        """
        order = keys or ["tenant_id", "company_id", "user_id"]
        segments: list[str] = []
        for key in order:
            value = getattr(self, key, None)
            if value is None or value == "":
                continue
            segments.append(str(value).replace("/", "_"))
        return segments

    def as_filter_dict(self) -> dict[str, str]:
        """Non-None fields as a plain dict (useful for SQL builders)."""
        out: dict[str, str] = {}
        if self.tenant_id is not None:
            out["tenant_id"] = self.tenant_id
        if self.company_id is not None:
            out["company_id"] = self.company_id
        if self.user_id is not None:
            out["user_id"] = self.user_id
        return out
