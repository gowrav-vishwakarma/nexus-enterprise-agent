"""Token counting utilities for LLM provider messages."""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TokenCounter:
    """Utility class to count/estimate tokens in strings and messages."""

    @classmethod
    def count_string(cls, text: str, model: str = "gpt-4o") -> int:
        """Count the number of tokens in a string using tiktoken."""
        if not text:
            return 0
        try:
            import tiktoken
            # Map common models to standard encodings
            encoding_name = "cl100k_base"
            if "gpt-4" in model or "gpt-3.5" in model:
                try:
                    encoding = tiktoken.encoding_for_model(model)
                except KeyError:
                    encoding = tiktoken.get_encoding("cl100k_base")
            elif "o1" in model or "o3" in model:
                encoding = tiktoken.get_encoding("o200k_base")
            else:
                encoding = tiktoken.get_encoding(encoding_name)
            
            return len(encoding.encode(text))
        except ImportError:
            # Fallback to rough estimation (4 chars per token)
            return len(text) // 4
        except Exception as e:
            logger.debug("Failed to count tokens with tiktoken: %s", e)
            return len(text) // 4

    @classmethod
    def count_messages(cls, messages: list[dict[str, Any]], model: str = "gpt-4o") -> int:
        """Count the number of tokens in a messages list."""
        try:
            import tiktoken
            try:
                encoding = tiktoken.encoding_for_model(model)
            except KeyError:
                encoding = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            # Fallback estimation
            total = 0
            for msg in messages:
                total += cls.count_string(msg.get("content") or "", model)
                # Estimate role overhead
                total += 4
            return total

        # tiktoken message counting rules for gpt-3.5-turbo and gpt-4
        tokens_per_message = 3
        tokens_per_name = 1

        if "gpt-3.5-turbo-0301" in model:
            tokens_per_message = 4
            tokens_per_name = -1

        num_tokens = 0
        for message in messages:
            num_tokens += tokens_per_message
            for key, value in message.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    # Handle tool calls or complex content structures
                    for item in value:
                        if isinstance(item, dict):
                            num_tokens += len(encoding.encode(str(item)))
                elif isinstance(value, dict):
                    num_tokens += len(encoding.encode(str(value)))
                else:
                    num_tokens += len(encoding.encode(str(value)))
                if key == "name":
                    num_tokens += tokens_per_name

        num_tokens += 3  # every reply is primed with assistant
        return num_tokens

    @classmethod
    def estimate_tool_schema_overhead(cls, tools: list[dict[str, Any]], model: str = "gpt-4o") -> int:
        """Estimate the token count of tool definitions."""
        if not tools:
            return 0
        # Convert tool schemas to JSON-like representation to count
        import json
        schema_str = json.dumps(tools)
        return cls.count_string(schema_str, model)
