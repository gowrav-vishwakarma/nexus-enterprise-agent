"""Extract structured tool calls from model text (Hermes/Nemotron/Gemma XML).

Some OpenAI-compatible models emit ``<tool_call>`` XML in ``content`` or
``reasoning`` instead of native ``tool_calls``. Nexus promotes these to
``ToolCallRequest`` so tools run and user-visible text is stripped before save.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Optional

from nexus.llm.response import LLMResponse, ToolCallRequest

_TOOL_CALL_BLOCK = re.compile(r"<tool_call>([\s\S]*?)</tool_call>", re.IGNORECASE)
_FUNCTION_TAG = re.compile(r"<function=([\w_.]+)>([\s\S]*?)</function>", re.IGNORECASE)
_PARAMETER_TAG = re.compile(r"<parameter=([\w_]+)>([\s\S]*?)</parameter>", re.IGNORECASE)
_GEMMA_TOOL_CALL = re.compile(
    r"<\|tool_call>\s*call:\s*([\w_]+)\s*(\{[\s\S]*?\})\s*<tool_call\|>",
    re.IGNORECASE,
)

EMPTY_ASSISTANT_PLACEHOLDER = "(prior step omitted)"
REASONING_ONLY_PLACEHOLDER = "(no response)"


def _coerce_parameter_value(raw: str) -> Any:
    param_value = raw.strip()
    if param_value.lower() == "true":
        return True
    if param_value.lower() == "false":
        return False
    if param_value.lower() == "null" or param_value == "":
        return None
    try:
        return json.loads(param_value)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        if "." in param_value or "e" in param_value.lower():
            return float(param_value)
        return int(param_value)
    except ValueError:
        return param_value


def _parse_one_nemotron_block(body: str, *, id_suffix: str) -> Optional[ToolCallRequest]:
    function_match = _FUNCTION_TAG.search(body)
    if not function_match:
        return None
    tool_name = function_match.group(1).strip()
    if not tool_name:
        return None
    function_body = function_match.group(2)
    args: dict[str, Any] = {}
    for param_match in _PARAMETER_TAG.finditer(function_body):
        args[param_match.group(1).strip()] = _coerce_parameter_value(param_match.group(2))
    return ToolCallRequest(
        id=f"call_{id_suffix}",
        tool_name=tool_name,
        tool_input=args,
    )


def parse_nemotron_tool_calls(text: str) -> tuple[list[ToolCallRequest], str]:
    """Parse all Nemotron/Hermes ``<tool_call>`` blocks from *text*."""
    if not text:
        return [], text
    tool_calls: list[ToolCallRequest] = []
    for idx, match in enumerate(_TOOL_CALL_BLOCK.finditer(text)):
        parsed = _parse_one_nemotron_block(match.group(1), id_suffix=f"xml_{idx}_{uuid.uuid4().hex[:8]}")
        if parsed:
            tool_calls.append(parsed)
    cleaned = _TOOL_CALL_BLOCK.sub("", text).strip()
    return tool_calls, cleaned


def parse_gemma_tool_calls(text: str) -> tuple[list[ToolCallRequest], str]:
    """Parse Gemma-style ``<|tool_call>call:name{...}<tool_call|>`` blocks."""
    if not text:
        return [], text
    tool_calls: list[ToolCallRequest] = []
    for idx, match in enumerate(_GEMMA_TOOL_CALL.finditer(text)):
        tool_name = match.group(1).strip()
        args_str = match.group(2).strip()
        args_str = re.sub(
            r'<\|"\|>([\s\S]*?)<\|"\|>',
            lambda m: json.dumps(m.group(1)),
            args_str,
        )
        args_str = args_str.replace('<|"|>', '"')
        args_str = re.sub(r"([{,]\s*)([a-zA-Z_]\w*)(\s*:)", r'\1"\2"\3', args_str)
        try:
            args = json.loads(args_str)
        except Exception:
            args = {}
        if not isinstance(args, dict):
            args = {}
        tool_calls.append(
            ToolCallRequest(
                id=f"call_gemma_{idx}_{uuid.uuid4().hex[:8]}",
                tool_name=tool_name,
                tool_input=args,
            )
        )
    cleaned = _GEMMA_TOOL_CALL.sub("", text).strip()
    return tool_calls, cleaned


def extract_tool_calls_from_text(text: Optional[str]) -> tuple[list[ToolCallRequest], Optional[str]]:
    """Try Nemotron then Gemma parsers; return tool calls and cleaned text."""
    if not text or not text.strip():
        return [], text
    nemotron_calls, after_nemotron = parse_nemotron_tool_calls(text)
    if nemotron_calls:
        return nemotron_calls, after_nemotron or None
    gemma_calls, after_gemma = parse_gemma_tool_calls(text)
    if gemma_calls:
        return gemma_calls, after_gemma or None
    return [], text


def promote_content_tool_calls(response: LLMResponse) -> LLMResponse:
    """When native tool_calls are empty, parse XML from content and/or reasoning."""
    if response.tool_calls:
        return response
    content_calls, cleaned_content = extract_tool_calls_from_text(response.content)
    if content_calls:
        return response.model_copy(
            update={"tool_calls": content_calls, "content": cleaned_content},
        )
    reasoning_calls, cleaned_reasoning = extract_tool_calls_from_text(response.reasoning)
    if reasoning_calls:
        return response.model_copy(
            update={
                "tool_calls": reasoning_calls,
                "reasoning": cleaned_reasoning or None,
            },
        )
    return response


def _has_assistant_substance(content: Any, tool_calls: Any) -> bool:
    if tool_calls:
        if isinstance(tool_calls, list) and len(tool_calls) > 0:
            return True
    if content is None:
        return False
    if isinstance(content, str):
        return bool(content.strip())
    return bool(content)


def sanitize_assistant_llm_message(msg: dict[str, Any], *, placeholder: str) -> dict[str, Any]:
    """Ensure an assistant message is valid for OpenAI-compatible replay."""
    out = dict(msg)
    tool_calls = out.get("tool_calls")
    if tool_calls is not None and isinstance(tool_calls, list) and not tool_calls:
        out.pop("tool_calls", None)
        tool_calls = None
    if out.get("role") != "assistant":
        return out
    if _has_assistant_substance(out.get("content"), tool_calls):
        if tool_calls is None and "tool_calls" in out:
            out.pop("tool_calls", None)
        return out
    out.pop("tool_calls", None)
    out["content"] = placeholder
    return out


def build_assistant_llm_message(
    *,
    content: Optional[str],
    tool_calls: list[ToolCallRequest],
    placeholder: str = REASONING_ONLY_PLACEHOLDER,
) -> dict[str, Any]:
    """Build a provider-safe assistant dict for turn persistence."""
    from nexus.llm.tool_format import tool_calls_to_openai_messages

    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls_to_openai_messages(tool_calls)
    return sanitize_assistant_llm_message(msg, placeholder=placeholder)
