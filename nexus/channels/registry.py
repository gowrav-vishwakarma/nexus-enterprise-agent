"""Registry of channel adapters, declared like tool plugins in a manifest."""

from __future__ import annotations

from typing import Iterator

from nexus.channels.base import ChannelAdapter


class ChannelRegistry:
    """Holds channel adapters keyed by name."""

    def __init__(self) -> None:
        self._channels: dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter under its ``name``."""
        self._channels[adapter.name] = adapter

    def get(self, name: str) -> ChannelAdapter:
        """Return the adapter registered under ``name``."""
        if name not in self._channels:
            raise KeyError(
                f"Channel {name!r} not registered. Available: {sorted(self._channels)}"
            )
        return self._channels[name]

    def has(self, name: str) -> bool:
        """True if a channel with this name is registered."""
        return name in self._channels

    def names(self) -> list[str]:
        """List registered channel names."""
        return sorted(self._channels)

    def __iter__(self) -> Iterator[ChannelAdapter]:
        return iter(self._channels.values())
