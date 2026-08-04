"""Artifact storage protocol."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from nexus.scope import ScopeLevel, scope_key
from nexus.storage.paths import sanitize_segment
from nexus.tools.context import RunContext


class ArtifactMeta(BaseModel):
    id: str
    filename: str
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class ArtifactStore(Protocol):
    async def put(
        self, ctx: RunContext, data: bytes, *, filename: str, content_type: str = "application/octet-stream"
    ) -> ArtifactMeta: ...

    async def get(self, ctx: RunContext, artifact_id: str) -> Optional[bytes]: ...


class LocalArtifactStore:
    """Store artifacts under tenant/user scoped directories.

    Scope values and filenames arrive from request data, so every path segment is
    sanitized and the final path is checked to be inside ``root``. Without that a
    tenant id of ``../../etc`` would write outside the store.
    """

    def __init__(self, root: str = "./artifacts"):
        self.root = Path(root).resolve()

    def _dir(self, ctx: RunContext) -> Path:
        key = scope_key(ctx, ScopeLevel.USER, "artifacts")
        path = self.root
        for segment in key.split(":"):
            path = path / sanitize_segment(segment, fallback="_")
        path = self._ensure_inside(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_inside(self, path: Path) -> Path:
        resolved = (self.root / path).resolve() if not path.is_absolute() else path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError(f"Artifact path escapes the store root: {path}")
        return resolved

    async def put(
        self,
        ctx: RunContext,
        data: bytes,
        *,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> ArtifactMeta:
        aid = str(uuid.uuid4())
        safe_name = sanitize_segment(filename, fallback="artifact")
        path = self._ensure_inside(self._dir(ctx) / f"{aid}_{safe_name}")
        path.write_bytes(data)
        return ArtifactMeta(
            id=aid,
            filename=filename,
            content_type=content_type,
            size_bytes=len(data),
        )

    async def get(self, ctx: RunContext, artifact_id: str) -> Optional[bytes]:
        safe_id = sanitize_segment(artifact_id, fallback="")
        if not safe_id:
            return None
        directory = self._dir(ctx)
        for path in directory.glob(f"{safe_id}_*"):
            return path.read_bytes()
        return None
