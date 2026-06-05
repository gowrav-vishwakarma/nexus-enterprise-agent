"""Persistence resolver protocol."""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from nexus.config.storage import SessionStorageConfig


@runtime_checkable
class PersistenceResolver(Protocol):
    """User implements to map tenant/user to storage configuration or bundles."""

    def resolve_storage_config(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
    ) -> SessionStorageConfig:
        """Return storage config for the given tenant/user scope."""
        ...

    def resolve_bundle(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
    ):
        """Optional: return a pre-built PersistenceBundle."""
        ...
