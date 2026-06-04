"""Serialization utilities for the Nexus Agent Framework."""

import json
import logging
from datetime import datetime, date
from typing import Any, Optional

logger = logging.getLogger(__name__)


def deep_serialize(obj: Any) -> Any:
    """Recursively serialize an object to JSON-compatible types.

    Handles:
    - datetime/date objects -> ISO format strings
    - set/frozenset -> lists
    - bytes -> hex strings
    - Enums -> their value
    - Objects with __dict__ -> dicts

    Args:
        obj: Object to serialize

    Returns:
        JSON-serializable object
    """
    if obj is None:
        return None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return [deep_serialize(item) for item in obj]
    if isinstance(obj, bytes):
        return obj.hex()
    if hasattr(obj, "__dict__"):
        return {k: deep_serialize(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, dict):
        return {str(k): deep_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [deep_serialize(item) for item in obj]
    return obj


def safe_json_loads(text: str, default: Optional[Any] = None) -> Any:
    """Safely parse JSON, returning default on failure.

    Args:
        text: JSON string to parse
        default: Value to return on parse failure

    Returns:
        Parsed JSON object or default
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug("Failed to parse JSON: %s. Error: %s", text[:100], e)
        return default


def safe_json_dumps(obj: Any, **kwargs: Any) -> str:
    """Safely serialize to JSON string.

    Args:
        obj: Object to serialize
        **kwargs: Additional kwargs for json.dumps

    Returns:
        JSON string, or empty string on failure
    """
    try:
        return json.dumps(deep_serialize(obj), **kwargs)
    except (TypeError, ValueError) as e:
        logger.debug("Failed to serialize to JSON: %s", e)
        return ""
