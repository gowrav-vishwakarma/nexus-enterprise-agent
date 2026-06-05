"""Inject cross-session user memory into system prompts when templates omit Jinja blocks."""

from nexus.config.memory import MemoryConfig

_USER_MEMORY_HEADING = "## About this user"


class MemoryPromptInjector:
    """Appends user memory facts to the system prompt (RCS-style fallback)."""

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

        lines = [f"- {key}: {value}" for key, value in facts.items()]
        block = f"{_USER_MEMORY_HEADING}\n" + "\n".join(lines)
        if system_message:
            return f"{system_message.rstrip()}\n\n{block}"
        return block
