"""Structured output validation for agent runs."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, ValidationError as PydanticValidationError

from nexus.errors import ValidationError

logger = logging.getLogger(__name__)


def result_type_schema(result_type: type) -> dict[str, Any]:
    """Return JSON schema for a Pydantic model or dict type."""
    if isinstance(result_type, type) and issubclass(result_type, BaseModel):
        return result_type.model_json_schema()
    return {"type": "object"}


def validate_structured_result(
    content: Optional[str],
    result_type: type,
) -> dict[str, Any]:
    """Parse assistant content as JSON and validate against result_type."""
    if not content or not content.strip():
        raise ValidationError("Structured output expected but assistant returned empty content")
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Structured output is not valid JSON: {exc}") from exc

    if isinstance(result_type, type) and issubclass(result_type, BaseModel):
        try:
            model = result_type.model_validate(raw)
            return model.model_dump()
        except PydanticValidationError as exc:
            raise ValidationError(f"Structured output validation failed: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValidationError("Structured output must be a JSON object")
    return raw


def format_validation_retry_message(error: ValidationError) -> str:
    """User message injected when structured output validation fails."""
    return (
        "Your previous response did not match the required output schema. "
        f"Validation error: {error}. "
        "Respond again with valid JSON matching the schema."
    )
