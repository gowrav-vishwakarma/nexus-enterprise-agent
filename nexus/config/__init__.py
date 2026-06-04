"""Configuration models for the Nexus Agent Framework."""

from .agent import AgentConfig, AgentGroupConfig, AgentPersonaConfig
from .llm import LLMProviderConfig
from .rcs import RuntimeContextSummarizerConfig, ServerCompactorConfig
from .memory import MemoryConfig
from .storage import SessionStorageConfig
from .defaults import (
    DEFAULT_RCS_SYSTEM_BLOCK,
    DEFAULT_COMPACTOR_PROMPT,
    DEFAULT_SYSTEM_TEMPLATE,
    DEFAULT_ENTITY_EXTRACTION_PROMPT,
)

__all__ = [
    "AgentConfig",
    "AgentGroupConfig",
    "AgentPersonaConfig",
    "LLMProviderConfig",
    "RuntimeContextSummarizerConfig",
    "ServerCompactorConfig",
    "MemoryConfig",
    "SessionStorageConfig",
    "DEFAULT_RCS_SYSTEM_BLOCK",
    "DEFAULT_COMPACTOR_PROMPT",
    "DEFAULT_SYSTEM_TEMPLATE",
    "DEFAULT_ENTITY_EXTRACTION_PROMPT",
]
