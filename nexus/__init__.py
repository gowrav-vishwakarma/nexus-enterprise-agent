"""Nexus Agent Framework - A SaaS-ready, context-efficient multi-agent framework.

Key features:
- Context-First Architecture with Runtime Context Summarization (RCS)
- SaaS-Native (zero global state, all config per-call)
- Provider-Agnostic LLM layer
- Pluggable persistence (SQLite, PostgreSQL, Redis, File, Memory)
- Type-safe by default (Pydantic v2)
- Observable via structured events

Example usage:
    from nexus import AgentConfig, AgentRunner, LLMProviderConfig
    from nexus.tools.registry import ToolRegistry

    config = AgentConfig(
        name="researcher",
        llm=LLMProviderConfig(
            provider="openai",
            model="gpt-4o",
            api_key="sk-...",
        ),
        persona={"role": "Researcher", "goal": "Answer questions"},
    )

    registry = ToolRegistry()
    runner = AgentRunner(config=config, tool_registry=registry)
    result = await runner.run("What is AI?")
"""

from nexus.config import (
    AgentConfig,
    AgentGroupConfig,
    AgentPersonaConfig,
    LLMProviderConfig,
    RuntimeContextSummarizerConfig,
    ServerCompactorConfig,
    MemoryConfig,
    ContextSummaryConfig,
    SessionStorageConfig,
    DEFAULT_RCS_SYSTEM_BLOCK,
    DEFAULT_COMPACTOR_PROMPT,
    DEFAULT_SYSTEM_TEMPLATE,
    DEFAULT_ENTITY_EXTRACTION_PROMPT,
    DEFAULT_MEMORY_CURATOR_PROMPT,
    DEFAULT_SESSION_MEMORY_CURATOR_PROMPT,
    DEFAULT_CONTEXT_SUMMARY_PROMPT,
)
from nexus.runner.agent_runner import AgentRunner
from nexus.runner.hooks import TurnContext, TurnDecision, RunnerHooks, ToolCallContext, LLMCallContext
from nexus.scope import ScopeLevel, scope_key, scope_keys_from_config
from nexus.errors import NexusError, LLMError, ToolError, GuardrailError, TurnTimeoutError, ValidationError
from nexus.runner.result import AgentRunResult, AgentStreamEvent
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool, tool_plugin
from nexus.memory import (
    MemoryCurator,
    MemoryUpdate,
    CrossSessionMemoryStore,
    CrossSessionMemoryRecord,
    InMemoryCrossSessionMemoryStore,
    SQLiteCrossSessionMemoryStore,
    PostgreSQLCrossSessionMemoryStore,
    RedisCrossSessionMemoryStore,
    MemoryProvider,
    BuiltInSemanticMemoryProvider,
)
from nexus.rag.config import RAGConfig
from nexus.rag.protocol import RAGProvider
from nexus.persistence import PersistenceBundle, PersistenceFactory, PersistenceResolver
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.multiagent.results import AgentGroupResult
from nexus.orchestration import OrchestrationManifest, OrchestrationRuntime
from nexus.events import EventEmitted, NexusEventEmitter, NexusEventType, NexusEvent

from nexus.tools.registry import ToolRegistry
from nexus.session.manager import SessionManager
from nexus.runner.checkpoint import RunCheckpoint, checkpoint_from_session
from nexus.runner.structured_output import validate_structured_result

__version__ = "0.4.0"

__all__ = [
    # Version
    "__version__",
    # Config
    "AgentConfig",
    "AgentGroupConfig",
    "AgentPersonaConfig",
    "LLMProviderConfig",
    "RuntimeContextSummarizerConfig",
    "ServerCompactorConfig",
    "MemoryConfig",
    "ContextSummaryConfig",
    "SessionStorageConfig",
    "DEFAULT_RCS_SYSTEM_BLOCK",
    "DEFAULT_COMPACTOR_PROMPT",
    "DEFAULT_SYSTEM_TEMPLATE",
    "DEFAULT_ENTITY_EXTRACTION_PROMPT",
    "DEFAULT_MEMORY_CURATOR_PROMPT",
    "DEFAULT_SESSION_MEMORY_CURATOR_PROMPT",
    "DEFAULT_CONTEXT_SUMMARY_PROMPT",
    # Runner
    "AgentRunner",
    "AgentRunResult",
    "AgentStreamEvent",
    "TurnContext",
    "TurnDecision",
    "RunnerHooks",
    "ToolCallContext",
    "LLMCallContext",
    # Scope & errors
    "ScopeLevel",
    "scope_key",
    "scope_keys_from_config",
    "NexusError",
    "LLMError",
    "ToolError",
    "GuardrailError",
    "TurnTimeoutError",
    "ValidationError",
    # Registry & session (public surface)
    "ToolRegistry",
    "SessionManager",
    "RunCheckpoint",
    "checkpoint_from_session",
    "validate_structured_result",
    # Tools
    "RunContext",
    "tool",
    "tool_plugin",
    # Memory
    "MemoryCurator",
    "MemoryUpdate",
    "CrossSessionMemoryStore",
    "CrossSessionMemoryRecord",
    "InMemoryCrossSessionMemoryStore",
    "SQLiteCrossSessionMemoryStore",
    "PostgreSQLCrossSessionMemoryStore",
    "RedisCrossSessionMemoryStore",
    "MemoryProvider",
    "BuiltInSemanticMemoryProvider",
    "RAGConfig",
    "RAGProvider",
    # Persistence
    "PersistenceBundle",
    "PersistenceFactory",
    "PersistenceResolver",
    # Multi-agent
    "AgentOrchestrator",
    "AgentGroupResult",
    # Orchestration
    "OrchestrationManifest",
    "OrchestrationRuntime",
    # Events
    "NexusEventType",
    "NexusEvent",
    "EventEmitted",
    "NexusEventEmitter",
]
