"""Configuration models for the Nexus Agent Framework."""

from .agent import AgentConfig, AgentGroupConfig, AgentPersonaConfig
from .llm import LLMProviderConfig
from .rcs import RuntimeContextSummarizerConfig, ServerCompactorConfig
from .context_summary import ContextSummaryConfig
from .memory import MemoryConfig
from .storage import SessionStorageConfig
from nexus.skills.config import SkillsConfig
from .defaults import (
    DEFAULT_RCS_SYSTEM_BLOCK,
    DEFAULT_COMPACTOR_PROMPT,
    DEFAULT_SYSTEM_TEMPLATE,
    DEFAULT_ENTITY_EXTRACTION_PROMPT,
    DEFAULT_MEMORY_CURATOR_PROMPT,
    DEFAULT_SESSION_MEMORY_CURATOR_PROMPT,
    DEFAULT_CONTEXT_SUMMARY_PROMPT,
)

__all__ = [
    "AgentConfig",
    "AgentGroupConfig",
    "AgentPersonaConfig",
    "LLMProviderConfig",
    "RuntimeContextSummarizerConfig",
    "ServerCompactorConfig",
    "MemoryConfig",
    "ContextSummaryConfig",
    "SessionStorageConfig",
    "SkillsConfig",
    "DEFAULT_RCS_SYSTEM_BLOCK",
    "DEFAULT_COMPACTOR_PROMPT",
    "DEFAULT_SYSTEM_TEMPLATE",
    "DEFAULT_ENTITY_EXTRACTION_PROMPT",
    "DEFAULT_MEMORY_CURATOR_PROMPT",
    "DEFAULT_SESSION_MEMORY_CURATOR_PROMPT",
    "DEFAULT_CONTEXT_SUMMARY_PROMPT",
]
