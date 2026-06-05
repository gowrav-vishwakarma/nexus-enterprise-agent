"""Environment variable interpolation for manifest YAML values."""

from __future__ import annotations

import os
import re
from typing import Any

_ENV_PATTERN = re.compile(r"\$\{ENV:([^}|]+)(?:\|([^}]*))?\}")


def interpolate_env(value: Any) -> Any:
    """Recursively expand ``${ENV:VAR}`` and ``${ENV:VAR|default}`` in manifest data."""
    if isinstance(value, str):
        return _interpolate_string(value)
    if isinstance(value, list):
        return [interpolate_env(item) for item in value]
    if isinstance(value, dict):
        return {key: interpolate_env(item) for key, item in value.items()}
    return value


def _interpolate_string(value: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1).strip()
        default = match.group(2)
        env_value = os.getenv(var_name)
        if env_value is not None and env_value != "":
            return env_value
        if default is not None:
            return default
        return ""

    if "${ENV:" not in value:
        return value
    return _ENV_PATTERN.sub(_replace, value)
