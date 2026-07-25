"""Context update interceptor to extract RCS updates before tool execution."""

import logging
from typing import Any, Optional

from nexus.config.rcs import RuntimeContextSummarizerConfig
from nexus.session.models import AgentSession, ContextUpdate, ToolCallRecord
from nexus.events.models import RCSTCSummarizedEvent

logger = logging.getLogger(__name__)


class ContextUpdateInterceptor:
    """Interceptor that runs before tool calls to extract and apply RCS updates."""

    def __init__(self, event_emitter: Optional[Any] = None):
        self.event_emitter = event_emitter

    async def intercept(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        session: AgentSession,
        current_turn_index: int,
        storage_adapter: Any,  # StorageAdapter or SessionManager
        rcs_config: RuntimeContextSummarizerConfig,
    ) -> tuple[dict[str, Any], list[ContextUpdate]]:
        """Extract _context_updates, update storage, and return cleaned arguments."""
        if not rcs_config or not rcs_config.enabled:
            return tool_input, []

        # 1. Extract and pop _context_updates
        updates_raw = tool_input.pop(rcs_config.context_updates_param_name, [])
        if not updates_raw:
            return tool_input, []

        logger.debug("Intercepted _context_updates: %s", updates_raw)

        # 2. Parse and apply updates
        applied_updates = []
        for item in updates_raw:
            if not isinstance(item, dict):
                continue
            
            tc_id = item.get("tc_id")
            summary = item.get("summary")
            
            if not tc_id or summary is None:
                continue

            tc_id = tc_id.strip()
            summary = summary.strip()

            # Security: Validate TC ID belongs to current session turns
            target_tc: Optional[ToolCallRecord] = None
            for turn in session.turns:
                for tc in turn.tool_calls:
                    if tc.tc_id == tc_id:
                        target_tc = tc
                        break
                if target_tc:
                    break

            if not target_tc:
                # TC does not belong to this session or doesn't exist
                from nexus.events.models import NexusEvent, NexusEventType
                if self.event_emitter:
                    await self.event_emitter.emit(
                        NexusEvent(
                            event_type=NexusEventType.RCS_CROSS_SESSION_TC_REFERENCE,
                            session_id=session.session_id,
                            agent_id=session.agent_id,
                            turn_index=current_turn_index,
                            data={"tc_id": tc_id, "summary": summary}
                        )
                    )
                logger.warning("RCS: Invalid/Cross-session TC ID reference ignored: %s", tc_id)
                continue

            # Update in-memory session object for consistency in the current run loop
            target_tc.summarized_response = summary
            target_tc.summarized_by_turn = current_turn_index
            if summary == rcs_config.empty_summary_sentinel or summary == "":
                target_tc.is_dropped = True

            # 3. Save atomically to storage
            try:
                # Support both direct StorageAdapter or SessionManager wrapping it
                if hasattr(storage_adapter, "update_tc_summary"):
                    await storage_adapter.update_tc_summary(
                        session_id=session.session_id,
                        tc_id=tc_id,
                        summarized_response=summary,
                        summarized_by_turn=current_turn_index,
                        scope=session.to_scope(),
                    )
            except Exception as e:
                logger.error("Failed to write TC summary to storage: %s", e)

            # 4. Calculate savings — marginal, not from raw, to avoid
            # double-counting when the LLM re-summarizes an already-summarized TC.
            # Baseline: previous summarized tokens if already summarized, else raw.
            from nexus.llm.token_counter import TokenCounter
            old_tokens = (
                target_tc.tokens_summarized
                if target_tc.tokens_summarized is not None
                else target_tc.tokens_raw
            )
            new_tokens = TokenCounter.count_string(summary) if not target_tc.is_dropped else 0
            target_tc.tokens_summarized = new_tokens

            saved = max(0, old_tokens - new_tokens)
            session.total_tokens_saved_by_rcs += saved

            applied_updates.append(ContextUpdate(
                tc_id=tc_id,
                summary=summary,
                tokens_saved=saved,
            ))

            # 5. Emit event
            if self.event_emitter:
                await self.event_emitter.emit(
                    RCSTCSummarizedEvent(
                        session_id=session.session_id,
                        agent_id=session.agent_id,
                        turn_index=current_turn_index,
                        tc_id=tc_id,
                        tokens_raw=target_tc.tokens_raw,
                        tokens_summarized=new_tokens,
                        tokens_saved=saved,
                    )
                )

        return tool_input, applied_updates
