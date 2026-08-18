"""Build a MemoryProvider from MemoryConfig."""

from __future__ import annotations

from typing import Any, Optional

from nexus.config.memory import MemoryConfig
from nexus.memory.cross_session_store import CrossSessionMemoryStore
from nexus.memory.provider import MemoryProvider
from nexus.memory.providers.builtin_semantic import BuiltInSemanticMemoryProvider
from nexus.orchestration.imports import import_from_path


def build_memory_provider(
    config: MemoryConfig,
    store: Optional[CrossSessionMemoryStore] = None,
    *,
    agent_name: str = "",
    **extra: Any,
) -> Optional[MemoryProvider]:
    """Instantiate the configured memory provider, or ``None`` for the KV path.

    When ``config.provider`` is unset the runner keeps using
    ``CrossSessionMemoryStore`` directly (existing apps need no changes).
    """
    if not config.provider:
        return None

    kwargs = {**config.provider_config, **extra}

    if config.provider == "custom_class":
        if not config.provider_class:
            raise ValueError(
                "MemoryConfig.provider_class is required when provider is custom_class"
            )
        cls = import_from_path(config.provider_class)
        return cls(store=store, config=config, agent_name=agent_name, **kwargs)

    if config.provider == "mem0":
        from nexus.memory.providers.mem0 import Mem0MemoryProvider

        return Mem0MemoryProvider(config=config, **kwargs)

    if config.provider == "honcho":
        from nexus.memory.providers.honcho import HonchoMemoryProvider

        return HonchoMemoryProvider(config=config, **kwargs)

    return BuiltInSemanticMemoryProvider(
        store, config, agent_name=agent_name, **kwargs
    )
