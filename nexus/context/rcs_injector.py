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

        # Determine the system block to append
        rcs_block = rcs_config.rcs_system_block or (
            "## Context Management Protocol\n\n"
            "This conversation uses a context management system to keep your working memory efficient.\n\n"
            "**How it works:**\n"
            "- Tool results you have received are tagged [TC1], [TC2], etc. in your context.\n"
            "- These tags mean the full result is still present and available for compression.\n"
            "- When making any tool call, you may include a `_context_updates` list to compress "
            "or drop old TC results you have already processed.\n\n"
            "**When to compress:**\n"
            "- You have extracted the key facts from a large result and no longer need it verbatim.\n"
            "- A result was a dead end (nothing useful) — compress it to [].\n"
            "- A result was a large file/page you have finished analyzing.\n\n"
            "**When NOT to compress:**\n"
            "- You may need the exact content again later.\n"
            "- The result contains data you will reference repeatedly (e.g. a schema, a config file "
            "you are actively editing).\n\n"
            "**If you have nothing to compress:** pass `_context_updates: []` — do not omit the field.\n"
            "This confirms you reviewed past results and chose to keep them. (You may also simply "
            "omit the field entirely if your tool schema makes it optional — both are valid.)\n\n"
            "Results without a [TCn] tag are already compressed and cannot be re-summarized."
        )

        # Append block to system prompt
        if system_message:
            return f"{system_message.rstrip()}\n\n{rcs_block}"
        return rcs_block
