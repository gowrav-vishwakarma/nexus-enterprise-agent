"""Pydantic models for orchestration manifest documents."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from nexus.config.storage import SessionStorageConfig


class ManifestDefaults(BaseModel):
    """Optional default blocks merged into agents and groups."""

    agent: dict[str, Any] = Field(default_factory=dict)
    llm: dict[str, Any] = Field(default_factory=dict)
    group: dict[str, Any] = Field(default_factory=dict)


class OrchestrationManifestSchema(BaseModel):
    """Top-level manifest shape (friendly schema, not raw AgentConfig dump)."""

    version: str = Field(default="1")
    root: str = Field(..., description="Name of root agent or group")
    prompts_module: Optional[str] = Field(
        default=None,
        description="Path to companion prompts Python module relative to manifest file",
    )
    defaults: ManifestDefaults = Field(default_factory=ManifestDefaults)
    storage: SessionStorageConfig = Field(
        default_factory=lambda: SessionStorageConfig(adapter="memory")
    )
    plugins: dict[str, str] = Field(
        default_factory=dict,
        description="Plugin name -> import path (module.Class)",
    )
    agents: dict[str, dict[str, Any]] = Field(default_factory=dict)
    groups: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @field_validator("root")
    @classmethod
    def _root_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("root must be a non-empty agent or group name")
        return value
