"""Memory curator: a gated, size-limited writer of session memory.

The curator mirrors the ``ServerCompactor`` pattern: it is an optional component
that makes its own LLM call (or runs a full agent) with a dedicated prompt and
writes durable facts/notes back onto the session. Reading is automatic - stored
``entity_memory`` / ``working_memory`` are injected into the system prompt by the
context builder.

Memory is deliberately kept small: entities are capped at ``max_entities`` and
working memory is truncated to ``max_length``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from nexus.config.memory import EntityMemoryConfig, MemoryConfig, WorkingMemoryConfig
from nexus.memory.user_store import UserMemoryStore, resolve_user_namespace
from nexus.llm.proxy import LLMProxy
from nexus.session.models import AgentSession

logger = logging.getLogger(__name__)


def _parse_json_object(text: str) -> Optional[dict[str, Any]]:
    """Best-effort extraction of a single JSON object from LLM output."""
    if not text:
        return None

    cleaned = text.strip()

    # Strip markdown code fences if present.
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()

    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # Fallback: grab the outermost {...} span.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(cleaned[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


@dataclass
class MemoryUpdate:
    """A parsed, normalized memory update produced by the curator."""

    entities: dict[str, str] = field(default_factory=dict)
    # None means "no change"; a string (incl. "") is an explicit value.
    working_memory: Optional[str] = None

    def is_empty(self) -> bool:
        return not self.entities and not self.working_memory

    @classmethod
    def from_llm_output(cls, text: str) -> "MemoryUpdate":
        """Parse curator LLM output into a normalized update (tolerant of noise)."""
        data = _parse_json_object(text)
        if data is None:
            return cls()

        entities: dict[str, str] = {}
        raw_entities = data.get("entities")
        if isinstance(raw_entities, dict):
            for key, value in raw_entities.items():
                if value is None:
                    continue
                entities[str(key)] = str(value)

        working: Optional[str] = None
        raw_working = data.get("working_memory")
        # Only treat a non-empty string as an explicit update so the curator does
        # not accidentally wipe existing notes by returning "".
        if isinstance(raw_working, str) and raw_working.strip():
            working = raw_working

        return cls(entities=entities, working_memory=working)

    def apply_to_session(
        self,
        session: AgentSession,
        entity_cfg: EntityMemoryConfig,
        working_cfg: WorkingMemoryConfig,
    ) -> tuple[bool, bool]:
        """Merge this update into the session, enforcing size caps.

        Returns ``(entity_changed, working_changed)``.
        """
        entity_changed = False
        working_changed = False

        if entity_cfg.enabled and self.entities:
            merged = {**session.entity_memory, **self.entities}
            if len(merged) > entity_cfg.max_entities:
                # Keep the most recently touched entries (dict preserves order).
                merged = dict(list(merged.items())[-entity_cfg.max_entities :])
            if merged != session.entity_memory:
                session.entity_memory = merged
                entity_changed = True

        if working_cfg.enabled and self.working_memory:
            new_working = self.working_memory[: working_cfg.max_length]
            if new_working != session.working_memory:
                session.working_memory = new_working
                working_changed = True

        return entity_changed, working_changed


class MemoryCurator:
    """Extracts durable memory from a session via a gated LLM call or agent."""

    def __init__(
        self,
        config: Optional[MemoryConfig],
        llm_proxy: LLMProxy,
        session_manager: Any,
        tool_registry: Any = None,
        run_context: Any = None,
        event_emitter: Any = None,
        user_memory_store: Optional[UserMemoryStore] = None,
        agent_name: str = "",
    ):
        self.config = config or MemoryConfig()
        self.llm_proxy = llm_proxy
        self.session_manager = session_manager
        self.tool_registry = tool_registry
        self.run_context = run_context
        self.event_emitter = event_emitter
        self.user_memory_store = user_memory_store
        self.agent_name = agent_name
        self._last_curated_turn: Optional[int] = None

    @property
    def active(self) -> bool:
        """True only if memory is enabled and at least one channel is on."""
        return bool(
            self.config.enabled
            and (self.config.entity.enabled or self.config.working.enabled)
        )

    def should_trigger(self, turn_index: int, at_end: bool) -> bool:
        """Decide whether to run the curator at this point."""
        if not self.active:
            return False

        if at_end:
            if not self.config.extract_at_end:
                return False
            # Avoid a redundant end-run if we just curated this same turn.
            return self._last_curated_turn != turn_index

        if self.config.extract_after_each_turn:
            return True

        interval = self.config.extraction_interval
        if interval and interval > 0:
            return (turn_index + 1) % interval == 0
        return False

    async def curate(self, session: AgentSession, turn_index: int) -> MemoryUpdate:
        """Run one curation pass; persist + emit events on change."""
        if not self.active:
            return MemoryUpdate()

        conversation = self._build_conversation_digest(session)
        if not conversation.strip():
            return MemoryUpdate()

        try:
            if self.config.curator_agent is not None:
                raw = await self._run_curator_agent(session, conversation)
            else:
                raw = await self._run_curator_llm(session, conversation)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("MemoryCurator: curation failed, skipping: %s", exc)
            return MemoryUpdate()

        update = MemoryUpdate.from_llm_output(raw or "")
        entity_changed, working_changed = update.apply_to_session(
            session, self.config.entity, self.config.working
        )
        self._last_curated_turn = turn_index

        if entity_changed or working_changed:
            await self.session_manager.save_session(session)
            await self._emit_events(
                session, turn_index, entity_changed, working_changed, update
            )

        if session.entity_memory:
            await self._persist_user_memory(session, turn_index)

        return update

    async def _persist_user_memory(
        self, session: AgentSession, turn_index: int
    ) -> None:
        """Promote session entity facts to cross-session user memory."""
        user_cfg = self.config.user
        if not user_cfg.enabled or not user_cfg.persist_from_curator:
            return
        if not self.user_memory_store:
            return
        ctx = self.run_context
        if not ctx or not getattr(ctx, "user_id", None):
            logger.debug(
                "MemoryCurator: skipping user memory persist (no user_id on RunContext)"
            )
            return

        namespace = resolve_user_namespace(user_cfg.namespace, self.agent_name)
        try:
            record = await self.user_memory_store.merge_entities(
                getattr(ctx, "tenant_id", None),
                ctx.user_id,
                namespace,
                session.entity_memory,
                max_entities=user_cfg.max_entities,
            )
            if self.event_emitter and record.entity_memory:
                from nexus.events.models import NexusEvent, NexusEventType

                await self.event_emitter.emit(
                    NexusEvent(
                        event_type=NexusEventType.ENTITY_EXTRACTED,
                        session_id=session.session_id,
                        agent_id=session.agent_id,
                        turn_index=turn_index,
                        data={
                            "scope": "user",
                            "entity_count": len(record.entity_memory),
                            "namespace": namespace,
                        },
                    )
                )
        except Exception as exc:
            logger.warning("MemoryCurator: user memory persist failed: %s", exc)

    def _build_conversation_digest(self, session: AgentSession) -> str:
        """Compact recent user/assistant exchanges, bounded by char budget."""
        lines: list[str] = []
        for turn in session.turns:
            if turn.user_message:
                lines.append(f"User: {turn.user_message}")
            for msg in turn.llm_messages:
                if msg.get("role") == "assistant" and msg.get("content"):
                    lines.append(f"Assistant: {msg['content']}")

        text = "\n".join(lines)
        limit = self.config.max_conversation_chars
        if len(text) > limit:
            # Keep the most recent content.
            text = text[-limit:]
        return text

    async def _run_curator_llm(self, session: AgentSession, conversation: str) -> str:
        """Single dedicated LLM call with the curator prompt."""
        proxy = self.llm_proxy
        if self.config.curator_llm is not None:
            proxy = LLMProxy(self.config.curator_llm)

        prompt = (
            self.config.get_curator_prompt()
            .replace(
                "{existing_entities}",
                json.dumps(session.entity_memory, ensure_ascii=False),
            )
            .replace("{existing_working}", session.working_memory or "")
            .replace("{conversation}", conversation)
        )

        response = await proxy.chat(messages=[{"role": "user", "content": prompt}])
        return response.content or ""

    async def _run_curator_agent(self, session: AgentSession, conversation: str) -> str:
        """Run a full AgentConfig as the curator (own prompt/tools).

        The curator agent has memory force-disabled to prevent recursion and runs
        in an isolated session so it never pollutes the main conversation.
        """
        from nexus.runner.agent_runner import AgentRunner
        from nexus.tools.context import RunContext

        curator_cfg = self.config.curator_agent.model_copy(deep=True)
        # Recursion guard: the curator must not itself curate.
        curator_cfg.memory = MemoryConfig(enabled=False)

        sub_session_id = f"{session.session_id}__memcurator"
        sub_runner = AgentRunner(
            config=curator_cfg,
            tool_registry=self.tool_registry,
            storage_config=self.session_manager,
            run_context=RunContext(
                tenant_id=getattr(self.run_context, "tenant_id", None),
                user_id=getattr(self.run_context, "user_id", None),
                session_id=sub_session_id,
            ),
            event_emitter=self.event_emitter,
        )

        user_msg = (
            "Existing entities (JSON): "
            f"{json.dumps(session.entity_memory, ensure_ascii=False)}\n"
            f"Existing working memory: {session.working_memory or ''}\n\n"
            f"Recent conversation:\n{conversation}"
        )
        result = await sub_runner.run(
            user_message=user_msg, session_id=sub_session_id
        )
        return result.final_response or ""

    async def _emit_events(
        self,
        session: AgentSession,
        turn_index: int,
        entity_changed: bool,
        working_changed: bool,
        update: MemoryUpdate,
    ) -> None:
        if not self.event_emitter:
            return

        from nexus.events.models import NexusEvent, NexusEventType

        if entity_changed:
            await self.event_emitter.emit(
                NexusEvent(
                    event_type=NexusEventType.ENTITY_EXTRACTED,
                    session_id=session.session_id,
                    agent_id=session.agent_id,
                    turn_index=turn_index,
                    data={
                        "entity_count": len(session.entity_memory),
                        "updated_keys": list(update.entities.keys()),
                    },
                )
            )

        if working_changed:
            await self.event_emitter.emit(
                NexusEvent(
                    event_type=NexusEventType.WORKING_MEMORY_UPDATED,
                    session_id=session.session_id,
                    agent_id=session.agent_id,
                    turn_index=turn_index,
                    data={"length": len(session.working_memory)},
                )
            )
