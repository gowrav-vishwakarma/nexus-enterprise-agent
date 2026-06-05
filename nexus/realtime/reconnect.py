"""Reconnect helpers for realtime connections (exponential backoff + jitter)."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def connect_with_retry(
    connect: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    jitter: float = 0.25,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """Call ``connect`` until it succeeds or retries are exhausted.

    Uses exponential backoff with jitter. Re-raises the last error if all
    attempts fail. ``asyncio.CancelledError`` is never swallowed.
    """
    attempt = 0
    last_exc: Optional[BaseException] = None
    while attempt <= max_retries:
        try:
            return await connect()
        except asyncio.CancelledError:
            raise
        except retry_on as exc:  # type: ignore[misc]
            last_exc = exc
            if attempt == max_retries:
                break
            delay = min(max_delay, base_delay * (2**attempt))
            delay += random.uniform(0, jitter)
            logger.warning(
                "Realtime connect failed (attempt %d/%d): %s; retrying in %.2fs",
                attempt + 1,
                max_retries + 1,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
            attempt += 1
    assert last_exc is not None
    raise last_exc
