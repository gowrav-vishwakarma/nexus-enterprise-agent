"""Configuration models for the Nexus Agent Framework."""

from .agent import AgentConfig, AgentGroupConfig, AgentPersonaConfig
from .llm import LLMProviderConfig
from .rcs import RuntimeContextSummarizerConfig, ServerCompactorConfig
from .memory import (
    SessionMemoryConfig,
    EntityMemoryConfig,
    WorkingMemoryConfig,
    CrossSessionMemoryConfig,
)
from .storage import SessionStorageConfig
from nexus.skills.config import SkillsConfig
from .defaults import (
    DEFAULT_RCS_SYSTEM_BLOCK,
    DEFAULT_COMPACTOR_PROMPT,
    DEFAULT_SYSTEM_TEMPLATE,
    DEFAULT_ENTITY_EXTRACTION_PROMPT,
    DEFAULT_SESSION_MEMORY_CURATOR_PROMPT,
)

__all__ = [
    "AgentConfig",
    "AgentGroupConfig",
    "AgentPersonaConfig",
    "LLMProviderConfig",
    "RuntimeContextSummarizerConfig",
    "ServerCompactorConfig",
    "SessionMemoryConfig",
    "EntityMemoryConfig",
    "WorkingMemoryConfig",
    "CrossSessionMemoryConfig",
    "SessionStorageConfig",
    "SkillsConfig",
    "DEFAULT_RCS_SYSTEM_BLOCK",
    "DEFAULT_COMPACTOR_PROMPT",
    "DEFAULT_SYSTEM_TEMPLATE",
    "DEFAULT_ENTITY_EXTRACTION_PROMPT",
    "DEFAULT_SESSION_MEMORY_CURATOR_PROMPT",
]
