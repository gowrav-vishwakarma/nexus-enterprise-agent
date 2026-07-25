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
from nexus.runner.hooks import TurnContext, TurnDecision
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
)
from nexus.persistence import PersistenceBundle, PersistenceFactory, PersistenceResolver
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.multiagent.results import AgentGroupResult
from nexus.orchestration import OrchestrationManifest, OrchestrationRuntime
from nexus.events import EventEmitted, NexusEventEmitter, NexusEventType, NexusEvent

__version__ = "0.2.1"

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
