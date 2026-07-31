"""Context window builder for the Nexus Agent Framework."""

import copy
import json
import logging
from datetime import datetime
from typing import Any, Optional

from nexus.config.agent import AgentConfig
from nexus.context.memory_injector import MemoryPromptInjector
from nexus.context.rcs_injector import RCSSystemPromptInjector
from nexus.context.summary_injector import SummaryPromptInjector
from nexus.session.models import AgentSession, ToolCallRecord, TurnRecord
from nexus.tools.context import RunContext
from nexus.utils.jinja import render_system_prompt
from nexus.llm.content_tool_calls import EMPTY_ASSISTANT_PLACEHOLDER, sanitize_assistant_llm_message
from nexus.llm.token_counter import TokenCounter

logger = logging.getLogger(__name__)

FALLBACK_USER_MESSAGE = "Continue."

OVERSIZED_TOOL_RESULT_NOTICE = (
    "Result not included: it was {tokens} tokens, which does not fit the remaining "
    "context budget. Re-run this tool with a narrower scope (shorter date range, "
    "fewer rows or columns, filters, or pagination), or use a tool that returns "
    "aggregates instead of raw records."
)


class ContextWindowBuilder:
    """Builds and manages the message sequence for the LLM context window."""

    def __init__(self, event_emitter: Optional[Any] = None):
        self.event_emitter = event_emitter
        self.last_untrimmed_tokens: int = 0

    @staticmethod
    def _format_tool_signature(tc: ToolCallRecord, include_signature: bool) -> str:
        """Render ``tool_name(arg=value, ...)`` for a tool call.

        Excludes the injected ``_context_updates`` RCS parameter so the LLM
        never sees it as part of the tool's own arguments.
        """
        if not include_signature:
            return ""
        args_str = ", ".join(
            f"{k}={json.dumps(v)}"
            for k, v in tc.tool_input.items()
            if k != "_context_updates"
        )
        return f"{tc.tool_name}({args_str})"

    @staticmethod
    def _summary_text(tc: ToolCallRecord) -> str:
        """Return the usable summary for a TC, or ``""`` when it has none.

        A missing, empty, whitespace-only, or legacy ``"[]"`` value all mean the
        same thing: this tool call is simply not summarized, so its full raw
        response is used. ``"[]"`` was written by older versions to mark a
        result as dropped; it is now treated as "no summary".
        """
        summary = (tc.summarized_response or "").strip()
        return "" if summary == "[]" else summary

    @staticmethod
    def _coalesce_consecutive_assistants(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge adjacent assistant messages into one.

        Strict-alternation providers (Qwen, GLM, Kimi, Ollama) reject two
        assistant messages in a row, unlike OpenAI which tolerates it. A message
        carrying ``tool_calls`` is never merged: it is a discrete step that must
        stay paired with the ``tool`` messages answering its call ids.
        """
        out: list[dict[str, Any]] = []
        for msg in messages:
            prev = out[-1] if out else None
            mergeable = (
                prev is not None
                and prev.get("role") == "assistant"
                and msg.get("role") == "assistant"
                and not prev.get("tool_calls")
                and not msg.get("tool_calls")
                and isinstance(prev.get("content"), str)
                and isinstance(msg.get("content"), str)
            )
            if not mergeable:
                out.append(msg)
                continue

            joined = "\n\n".join(
                part for part in (prev["content"].strip(), msg["content"].strip()) if part
            )
            out[-1] = {**prev, "content": joined or prev["content"]}
        return out

    @staticmethod
    def _overflow_notice(tokens: int) -> str:
        return OVERSIZED_TOOL_RESULT_NOTICE.format(tokens=tokens)

    @staticmethod
    def _has_bare_user_message(messages: list[dict[str, Any]]) -> bool:
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return True
        return False

    @staticmethod
    def _ensure_user_query(
        messages: list[dict[str, Any]], anchor: Optional[str]
    ) -> list[dict[str, Any]]:
        """Insert a user message when trimming removed every bare user turn."""
        if ContextWindowBuilder._has_bare_user_message(messages):
            return messages

        text = (anchor or "").strip() or FALLBACK_USER_MESSAGE
        user_msg = {"role": "user", "content": text}
        if messages and messages[0].get("role") == "system":
            return [messages[0], user_msg, *messages[1:]]
        return [user_msg, *messages]

    def _degrade_oldest_tool(
        self,
        turns: list[TurnRecord],
        degraded_tc_ids: set[str],
    ) -> bool:
        """Mark the oldest unsummarized tool call for overflow-notice rendering."""
        for turn in turns:
            for tc in turn.tool_calls:
                if tc.tc_id in degraded_tc_ids:
                    continue
                if self._summary_text(tc):
                    continue
                degraded_tc_ids.add(tc.tc_id)
                return True
        return False

    def _turn_to_messages(
        self,
        turn: TurnRecord,
        *,
        rcs_enabled: bool,
        tc_tag_format: str,
        include_signature: bool,
        degraded_tc_ids: set[str],
    ) -> list[dict[str, Any]]:
        turn_messages: list[dict[str, Any]] = []

        if turn.user_message:
            turn_messages.append({"role": "user", "content": turn.user_message})

        for msg in turn.llm_messages:
            msg_copy = copy.deepcopy(msg)
            if msg_copy.get("role") == "assistant":
                msg_copy = sanitize_assistant_llm_message(
                    msg_copy, placeholder=EMPTY_ASSISTANT_PLACEHOLDER
                )
            turn_messages.append(msg_copy)

        for tc in turn.tool_calls:
            content = self._render_tool_message(
                tc=tc,
                rcs_enabled=rcs_enabled,
                tc_tag_format=tc_tag_format,
                include_signature=include_signature,
                degraded=tc.tc_id in degraded_tc_ids,
            )

            tool_call_id = f"call_{tc.tc_id}"
            for msg in turn.llm_messages:
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    tc_idx = turn.tool_calls.index(tc)
                    if tc_idx < len(msg["tool_calls"]):
                        tool_call_id = msg["tool_calls"][tc_idx].get("id", tool_call_id)

            turn_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": content,
                }
            )

        return turn_messages

    def _render_tool_message(
        self,
        tc: ToolCallRecord,
        rcs_enabled: bool,
        tc_tag_format: str,
        include_signature: bool,
        *,
        degraded: bool = False,
    ) -> str:
        """Render a tool result message according to its RCS status.

        A tool call always yields a tool message: RCS replaces the result body
        with a summary, it never removes the step.

        Rendering rules:
        - Summarized: keep the tool signature (``tool_name(args)``) so the LLM
          knows what was called and with what params, but DROP the ``[TCn]`` tag
          so the result is not eligible for re-summarization in a later turn.
          The summary text replaces the raw response.
        - Not summarized, RCS on: prefix with ``[TCn]`` tag (and signature when
          configured) so the LLM can target it via ``_context_updates``.
        - RCS off: raw response only.

        An empty, whitespace-only, or legacy ``"[]"`` summary counts as *not
        summarized*, so the full raw response is rendered with its tag. That
        keeps sessions written by older versions readable.
        """
        if degraded:
            tokens = tc.tokens_raw or TokenCounter.count_string(tc.raw_response)
            notice = self._overflow_notice(tokens)
            if rcs_enabled:
                tag = tc_tag_format.format(n=tc.tc_index)
                signature = self._format_tool_signature(tc, include_signature)
                prefix = f"{tag} {signature}\n" if signature else f"{tag}\n"
                return f"{prefix}{notice}"
            return notice

        summary = self._summary_text(tc)

        # Summarized — signature kept, [TCn] tag intentionally dropped
        if summary:
            signature = self._format_tool_signature(tc, include_signature)
            if signature:
                return f"{signature}\n{summary}"
            return summary

        # Not summarized
        if rcs_enabled:
            tag = tc_tag_format.format(n=tc.tc_index)
            signature = self._format_tool_signature(tc, include_signature)
            prefix = f"{tag} {signature}\n" if signature else f"{tag}\n"
            return f"{prefix}{tc.raw_response}"

        # RCS disabled: show raw response
        return tc.raw_response

    async def build(
        self,
        session: AgentSession,
        agent_config: AgentConfig,
        current_user_message: Optional[str] = None,
        token_budget: int = 100000,
        user_memory: Optional[dict[str, str]] = None,
        summary_text: str = "",
        run_context: Optional[RunContext] = None,
        skills_catalog: Optional[str] = None,
        explicit_skills_content: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Assemble the complete messages array for the LLM call.

        Applies RCS tagging, inline summaries, memory injection, and token pruning.
        """
        rcs_enabled = agent_config.rcs.enabled
        tc_tag_format = agent_config.rcs.tc_tag_format or "[TC{n}]"
        include_signature = agent_config.rcs.tc_tag_include_tool_signature

        # 1. Build and render System Prompt
        persona_dict = agent_config.persona.model_dump()
        memory_cfg = getattr(agent_config, "memory", None)
        summary_cfg = getattr(agent_config, "context_summary", None)
        facts = user_memory if user_memory is not None else {}
        memory_for_jinja = (
            facts
            if memory_cfg and memory_cfg.enabled and memory_cfg.inject_into_prompt
            else {}
        )
        summary_for_jinja = ""
        if (
            summary_cfg
            and summary_cfg.summarize_on is not None
            and summary_cfg.inject_into_prompt
        ):
            summary_for_jinja = summary_text or ""

        system_content = render_system_prompt(
            persona=persona_dict,
            user_memory=memory_for_jinja,
            summary_text=summary_for_jinja,
            current_date=datetime.now().strftime("%Y-%m-%d"),
            template=agent_config.persona.system_prompt or agent_config.persona.system_prompt_template,
            run_context=run_context,
            session=session,
        )

        system_content = MemoryPromptInjector.inject(
            system_content, facts, memory_cfg
        )
        system_content = SummaryPromptInjector.inject(
            system_content, summary_text or "", summary_cfg
        )

        # Inject RCS System Prompt Block if enabled
        if rcs_enabled:
            system_content = RCSSystemPromptInjector.inject(system_content, agent_config.rcs)

        if explicit_skills_content:
            system_content = f"{system_content}\n\n{explicit_skills_content}"

        if skills_catalog:
            system_content = f"{system_content}\n\n{skills_catalog}"

        system_message = {"role": "system", "content": system_content}

        # 2. Sliding-window budgeting over session turns.
        # Order when over budget: degrade oldest raw tool bodies, then drop whole turns.
        turns_in_window = list(session.turns)
        degraded_tc_ids: set[str] = set()
        turns_dropped = 0
        model = agent_config.llm.model

        anchor_user_message = current_user_message or next(
            (t.user_message for t in reversed(session.turns) if t.user_message),
            None,
        )

        current_messages: list[dict[str, Any]] = []
        if current_user_message:
            current_messages.append({"role": "user", "content": current_user_message})

        self.last_untrimmed_tokens = 0

        while True:
            flat_history: list[dict[str, Any]] = []
            for turn in turns_in_window:
                flat_history.extend(
                    self._turn_to_messages(
                        turn,
                        rcs_enabled=rcs_enabled,
                        tc_tag_format=tc_tag_format,
                        include_signature=include_signature,
                        degraded_tc_ids=degraded_tc_ids,
                    )
                )

            full_messages = [system_message] + flat_history + current_messages
            total_tokens = TokenCounter.count_messages(full_messages, model)

            if self.last_untrimmed_tokens == 0:
                self.last_untrimmed_tokens = total_tokens

            if total_tokens <= token_budget:
                break

            if self._degrade_oldest_tool(turns_in_window, degraded_tc_ids):
                continue

            if turns_in_window:
                turns_in_window.pop(0)
                turns_dropped += 1
                continue

            break

        if degraded_tc_ids or turns_dropped:
            logger.warning(
                "Context window over budget (%d > %d): degraded %d tool result(s), "
                "dropped %d turn(s).",
                self.last_untrimmed_tokens,
                token_budget,
                len(degraded_tc_ids),
                turns_dropped,
            )

        final_messages = self._coalesce_consecutive_assistants(
            self._ensure_user_query(
                [system_message] + flat_history + current_messages,
                anchor_user_message,
            )
        )

        # Emit observability event (awaited so it is not silently lost)
        if self.event_emitter:
            from nexus.events.models import RCSContextBuiltEvent
            all_tcs = [tc for turn in session.turns for tc in turn.tool_calls]
            tc_summarized_count = sum(1 for tc in all_tcs if self._summary_text(tc))
            tc_tags_count = len(all_tcs) - tc_summarized_count
            await self.event_emitter.emit(
                RCSContextBuiltEvent(
                    session_id=session.session_id,
                    agent_id=session.agent_id,
                    context_tokens=TokenCounter.count_messages(final_messages, agent_config.llm.model),
                    untrimmed_tokens=self.last_untrimmed_tokens,
                    turns_in_context=len(turns_in_window),
                    tc_tags_count=tc_tags_count,
                    tc_summarized_count=tc_summarized_count,
                    tools_degraded_count=len(degraded_tc_ids),
                    turns_dropped=turns_dropped,
                )
            )

        return final_messages

    def count_rcs_savings(
        self,
        messages: list[dict[str, Any]],
        session: AgentSession,
        agent_config: AgentConfig,
    ) -> int:
        """Compute the recurring input-token savings from RCS for the given context.

        For each tool message in ``messages`` whose TC has been summarized,
        compute what the message WOULD have been without RCS (raw rendering with
        tag + signature + raw_response) and return the total token difference.

        This gives the true recurring savings for the current turn — the input
        tokens saved by having summaries instead of raw results in context. The
        runner accumulates this across turns into
        ``session.cumulative_input_tokens_saved_by_rcs``.
        """
        if not agent_config.rcs.enabled:
            return 0

        model = agent_config.llm.model
        tc_tag_format = agent_config.rcs.tc_tag_format or "[TC{n}]"
        include_signature = agent_config.rcs.tc_tag_include_tool_signature

        # Map call_id → ToolCallRecord for quick lookup
        tc_by_call_id: dict[str, ToolCallRecord] = {}
        for turn in session.turns:
            for tc in turn.tool_calls:
                if tc.call_id:
                    tc_by_call_id[tc.call_id] = tc

        total_savings = 0

        for msg in messages:
            if msg.get("role") != "tool":
                continue
            call_id = msg.get("tool_call_id")
            tc = tc_by_call_id.get(call_id) if call_id else None
            if tc is None:
                continue
            if not self._summary_text(tc):
                continue

            actual_content = msg.get("content") or ""
            actual_tokens = TokenCounter.count_string(actual_content, model)

            tag = tc_tag_format.format(n=tc.tc_index)
            signature = self._format_tool_signature(tc, include_signature)
            counterfactual_prefix = f"{tag} {signature}\n" if signature else f"{tag}\n"
            counterfactual_content = f"{counterfactual_prefix}{tc.raw_response}"
            counterfactual_tokens = TokenCounter.count_string(counterfactual_content, model)

            total_savings += max(0, counterfactual_tokens - actual_tokens)

        return total_savings
