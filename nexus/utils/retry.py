"""Async retry utilities using tenacity."""

import asyncio
import logging
from typing import Any, Callable, TypeVar

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

R = TypeVar("R")


def retry_async(
    max_retries: int = 3,
    retry_delay: float = 1.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
):
    """Decorator for retrying async functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        retry_delay: Initial delay between retries in seconds
        retry_on: Tuple of exception types to retry on

    Returns:
        Decorated async function

    Example:
        @retry_async(max_retries=3, retry_delay=1.0)
        async def call_api():
            ...
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max_retries),
                wait=wait_exponential(multiplier=retry_delay, min=retry_delay),
                retry=retry_if_exception_type(retry_on),
                reraise=True,
            ):
                with attempt:
                    logger.debug(
                        "Retrying %s (attempt %d/%d)",
                        func.__name__,
                        attempt.retry_number,
                        max_retries,
                    )
                    return await func(*args, **kwargs)
        return wrapper
    return decorator


async def retry_with_backoff(
    func: Callable,
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> Any:
    """Retry an async function with exponential backoff.

    Args:
        func: Async callable to retry
        *args: Positional arguments for the callable
        max_retries: Maximum number of retries
        base_delay: Base delay in seconds (doubles each retry)
        retry_on: Exception types to retry on
        **kwargs: Keyword arguments for the callable

    Returns:
        Result of the function call

    Raises:
        Last exception if all retries fail
    """
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except retry_on as e:
            last_exception = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Attempt %d/%d failed for %s: %s. Retrying in %.1fs",
                    attempt + 1,
                    max_retries + 1,
                    func.__name__,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
    raise last_exception  # type: ignore[misc]
