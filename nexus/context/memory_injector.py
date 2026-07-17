"""Inject cross-session user memory into system prompts when templates omit Jinja blocks."""

from __future__ import annotations

from collections import OrderedDict

from nexus.config.memory import MemoryConfig

_USER_MEMORY_HEADING = "## About this user"


class MemoryPromptInjector:
    """Appends user memory facts to the system prompt (RCS-style fallback)."""

    @staticmethod
    def _store_title(memory_cfg: MemoryConfig, store_name: str) -> str:
        for store in memory_cfg.stores or []:
            if store.name == store_name:
                return (store.description or "").strip() or store.name
        return store_name

    @staticmethod
    def _format_block(facts: dict[str, str], memory_cfg: MemoryConfig | None) -> str:
        """Build the memory prompt block, with per-store sections when prefixed."""
        if not memory_cfg or not memory_cfg.stores:
            lines = [f"- {key}: {value}" for key, value in facts.items()]
            return f"{_USER_MEMORY_HEADING}\n" + "\n".join(lines)

        grouped: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()
        unprefixed: list[tuple[str, str]] = []
        known = {s.name for s in memory_cfg.stores}

        for key, value in facts.items():
            if "/" in key:
                store_name, _, rest = key.partition("/")
                if store_name in known and rest:
                    grouped.setdefault(store_name, []).append((rest, value))
                    continue
            unprefixed.append((key, value))

        parts: list[str] = [_USER_MEMORY_HEADING]
        # Preserve configured store order for always-inject stores.
        for store in memory_cfg.stores:
            entries = grouped.get(store.name)
            if not entries:
                continue
            title = MemoryPromptInjector._store_title(memory_cfg, store.name)
            parts.append(f"### {title}")
            parts.extend(f"- {k}: {v}" for k, v in entries)
        if unprefixed:
            parts.extend(f"- {k}: {v}" for k, v in unprefixed)
        return "\n".join(parts)

    @staticmethod
    def inject(
        system_message: str,
        facts: dict[str, str],
        memory_cfg: MemoryConfig | None,
    ) -> str:
        """Append user facts when memory injection is enabled and template lacks the block."""
        if not memory_cfg or not memory_cfg.enabled or not memory_cfg.inject_into_prompt:
            return system_message
        if not facts:
            return system_message
        if _USER_MEMORY_HEADING in system_message:
            return system_message

        block = MemoryPromptInjector._format_block(facts, memory_cfg)
        if system_message:
            return f"{system_message.rstrip()}\n\n{block}"
        return block
