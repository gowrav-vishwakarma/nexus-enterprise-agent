"""Persistence factory for session + cross-session memory wiring."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Optional

from nexus.config.storage import SessionStorageConfig
from nexus.memory.cross_session_store import (
    CrossSessionMemoryStore,
    InMemoryCrossSessionMemoryStore,
    PostgreSQLCrossSessionMemoryStore,
    RedisCrossSessionMemoryStore,
    SQLiteCrossSessionMemoryStore,
)
from nexus.persistence.resolver import PersistenceResolver
from nexus.session.adapters.base import StorageAdapter
from nexus.session.manager import SessionManager


@dataclass
class PersistenceBundle:
    """Matched session manager and cross-session memory store."""

    session_manager: SessionManager
    cross_session_memory_store: CrossSessionMemoryStore


class PersistenceFactory:
    """Convenience builder; users may construct adapters directly instead."""

    @staticmethod
    def create_session_adapter(config: SessionStorageConfig) -> StorageAdapter:
        return SessionManager._create_adapter_from_config(config)

    @staticmethod
    def create_cross_session_store(
        config: SessionStorageConfig,
        *,
        session_adapter: Optional[StorageAdapter] = None,
    ) -> CrossSessionMemoryStore:
        cfg = dict(config.adapter_config or {})

        if config.custom_memory_adapter_class:
            return load_custom_memory_store(
                config.custom_memory_adapter_class, cfg
            )

        adapter_type = config.adapter or "memory"

        if adapter_type in ("memory",):
            return InMemoryCrossSessionMemoryStore()

        if adapter_type in ("file", "sqlite"):
            from nexus.storage.paths import get_data_root

            return SQLiteCrossSessionMemoryStore(
                data_root=cfg.get("data_root", str(get_data_root())),
                tenant_scoped=cfg.get("tenant_scoped", True),
                db_path=cfg.get("db_path"),
            )

        if adapter_type == "postgresql":
            pool = getattr(session_adapter, "_pool", None) if session_adapter else None
            return PostgreSQLCrossSessionMemoryStore(pool=pool, **cfg)

        if adapter_type == "redis":
            client = getattr(session_adapter, "_redis", None) if session_adapter else None
            mem_cfg = dict(cfg)
            if client is not None:
                mem_cfg["client"] = client
            return RedisCrossSessionMemoryStore(**mem_cfg)

        return InMemoryCrossSessionMemoryStore()

    @classmethod
    def from_storage_config(
        cls,
        config: SessionStorageConfig,
        *,
        cross_session_enabled: bool = True,
    ) -> PersistenceBundle:
        session_adapter = cls.create_session_adapter(config)
        memory_store: CrossSessionMemoryStore
        if cross_session_enabled:
            memory_store = cls.create_cross_session_store(
                config, session_adapter=session_adapter
            )
        else:
            memory_store = InMemoryCrossSessionMemoryStore()
        return PersistenceBundle(
            session_manager=SessionManager(storage_adapter=session_adapter),
            cross_session_memory_store=memory_store,
        )

    @classmethod
    def from_resolver(
        cls,
        resolver: PersistenceResolver,
        tenant_id: Optional[str],
        user_id: Optional[str],
        *,
        cross_session_enabled: bool = True,
    ) -> PersistenceBundle:
        bundle = resolver.resolve_bundle(tenant_id, user_id)
        if bundle is not None:
            return bundle
        config = resolver.resolve_storage_config(tenant_id, user_id)
        return cls.from_storage_config(
            config, cross_session_enabled=cross_session_enabled
        )


def load_custom_adapter(class_path: str, adapter_config: dict[str, Any]) -> StorageAdapter:
    """Instantiate a user-provided StorageAdapter from an import path."""
    module_path, _, class_name = class_path.rpartition(".")
    if not module_path:
        raise ValueError(f"Invalid custom_adapter_class: {class_path}")
    module = import_module(module_path)
    adapter_cls = getattr(module, class_name)
    return adapter_cls(**adapter_config)


def load_custom_memory_store(
    class_path: str, adapter_config: dict[str, Any]
) -> CrossSessionMemoryStore:
    """Instantiate a user-provided CrossSessionMemoryStore from an import path."""
    module_path, _, class_name = class_path.rpartition(".")
    if not module_path:
        raise ValueError(f"Invalid custom_memory_adapter_class: {class_path}")
    module = import_module(module_path)
    store_cls = getattr(module, class_name)
    return store_cls(**adapter_config)
