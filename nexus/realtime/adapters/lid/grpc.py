"""gRPC LID client adapter."""

from __future__ import annotations

from typing import Optional

import grpc

from nexus.realtime.adapters.lid.base import LIDAdapter, LIDResult
from nexus.realtime.config import LIDConfig
from nexus.server.metadata import run_context_to_metadata
from nexus.server.proto import media_pb2, media_pb2_grpc
from nexus.server.resolve import resolve_grpc_target
from nexus.tools.context import RunContext


class GrpcLID(LIDAdapter):
    """LID via Nexus media gRPC server."""

    def __init__(
        self,
        config: LIDConfig,
        *,
        registry=None,
        run_context: Optional[RunContext] = None,
    ) -> None:
        super().__init__(config)
        self._registry = registry
        self._run_context = run_context
        self._target = resolve_grpc_target(
            base_url=config.base_url,
            server_ref=config.server_ref,
            registry=registry,
            tenant_id=run_context.tenant_id if run_context else None,
        )
        self._channel: Optional[grpc.aio.Channel] = None

    async def _stub(self) -> media_pb2_grpc.LidServiceStub:
        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(self._target)
        return media_pb2_grpc.LidServiceStub(self._channel)

    def _metadata(self):
        return run_context_to_metadata(self._run_context)

    async def detect(
        self, audio: bytes, *, fallback_language: str | None = None
    ) -> LIDResult:
        stub = await self._stub()
        fallback = fallback_language or self.config.fallback_language
        resp = await stub.DetectLanguage(
            media_pb2.LidRequest(
                pcm=audio,
                sample_rate=self.config.sample_rate,
                fallback_language=fallback,
            ),
            metadata=self._metadata(),
        )
        en_text = (resp.english_text or "").strip() or None
        return LIDResult(
            language=resp.language or fallback,
            confidence=resp.confidence or 0.0,
            english_text=en_text,
        )
