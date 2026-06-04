"""Memory configuration models."""

from typing import Optional

from pydantic import BaseModel, Field


class EntityMemoryConfig(BaseModel):
    """Configuration for entity memory (persistent facts across turns)."""

    enabled: bool = Field(default=False, description="Enable entity memory")
    max_entities: int = Field(default=100, ge=1, description="Max entities to store")
    extraction_interval: int = Field(
        default=3, ge=1, description="Extract entities every N turns"
    )
    extraction_prompt: str = Field(
        default="",
        description="Custom entity extraction prompt (empty = use default)",
    )

    def get_extraction_prompt(self) -> str:
        """Return the entity extraction prompt."""
        from nexus.config.defaults import DEFAULT_ENTITY_EXTRACTION_PROMPT

        return self.extraction_prompt or DEFAULT_ENTITY_EXTRACTION_PROMPT


class WorkingMemoryConfig(BaseModel):
    """Configuration for working memory (temporary notes across turns)."""

    enabled: bool = Field(default=False, description="Enable working memory")
    max_length: int = Field(default=2000, ge=100, description="Max character length")


class MemoryConfig(BaseModel):
    """Combined memory configuration."""

    entity: EntityMemoryConfig = Field(
        default_factory=EntityMemoryConfig, description="Entity memory settings"
    )
    working: WorkingMemoryConfig = Field(
        default_factory=WorkingMemoryConfig, description="Working memory settings"
    )
