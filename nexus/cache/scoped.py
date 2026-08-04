"""Scope-keyed caching hooks."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

from nexus.scope import ScopeLevel, scope_key
from nexus.tools.context import RunContext


class ScopedCache:
    """Simple TTL cache keyed by scope + hash."""

    def __init__(self, ttl_seconds: float = 300.0):
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def _key(self, ctx: RunContext, namespace: str, payload: Any) -> str:
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        return f"{scope_key(ctx, ScopeLevel.USER, namespace)}:{digest}"

    def get(self, ctx: RunContext, namespace: str, payload: Any) -> Optional[Any]:
        key = self._key(ctx, namespace, payload)
        entry = self._store.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.time() - ts > self.ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, ctx: RunContext, namespace: str, payload: Any, value: Any) -> None:
        key = self._key(ctx, namespace, payload)
        self._store[key] = (time.time(), value)
