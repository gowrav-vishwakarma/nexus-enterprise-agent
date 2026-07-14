"""Configuration models for Nexus media model servers."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ServerKind = Literal["stt", "tts", "vad", "lid"]


class ModelServerSpec(BaseModel):
    """One media model server (STT, TTS, VAD, or LID)."""

    kind: ServerKind = Field(..., description="Server type")
    engine: str = Field(..., description="Engine plugin id, e.g. conformer, parler, silero")
    host: str = Field(default="127.0.0.1")
    port: int = Field(..., ge=1, le=65535)
    device: Optional[str] = Field(default=None, description="cuda:0, cpu, etc.")
    replicas: int = Field(default=1, ge=1, description="TTS replica count")
    extra: dict[str, Any] = Field(default_factory=dict, description="Engine-specific options")

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"


class ServersConfig(BaseModel):
    """Named map of media servers (standalone servers.yaml or manifest servers: block)."""

    servers: dict[str, ModelServerSpec] = Field(default_factory=dict)

    def get(self, name: str) -> ModelServerSpec:
        if name not in self.servers:
            known = ", ".join(sorted(self.servers)) or "(none)"
            raise KeyError(f"Unknown server {name!r}; known: {known}")
        return self.servers[name]


class LauncherConfig(BaseModel):
    """Launcher behaviour."""

    health_timeout_s: float = Field(default=120.0, description="Max wait for server ready")
    health_interval_s: float = Field(default=0.5)
    stop_timeout_s: float = Field(default=10.0)
