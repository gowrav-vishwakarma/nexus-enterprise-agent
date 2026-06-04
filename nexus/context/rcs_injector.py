"""RCS system prompt injector to append the RCS protocol block to the system message."""

from nexus.config.rcs import RuntimeContextSummarizerConfig


class RCSSystemPromptInjector:
    """Injects the RCS contract explanation into the system prompt."""

    @staticmethod
    def inject(
        system_message: str,
        rcs_config: RuntimeContextSummarizerConfig,
    ) -> str:
        """Appends the RCS contract block to the system prompt if RCS is enabled."""
        if not rcs_config or not rcs_config.enabled:
            return system_message

        rcs_block = rcs_config.get_rcs_system_block()

        # Append block to system prompt
        if system_message:
            return f"{system_message.rstrip()}\n\n{rcs_block}"
        return rcs_block
