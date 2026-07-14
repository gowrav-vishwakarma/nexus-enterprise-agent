"""LLM adapters package for the Nexus Agent Framework.

All providers route through the single :class:`LiteLLMAdapter`. See
:mod:`nexus.llm.proxy` for how it is selected.
"""

from nexus.llm.adapters.base import LLMAdapter
from nexus.llm.adapters.litellm import LiteLLMAdapter, build_litellm_model_string

__all__ = [
    "LLMAdapter",
    "LiteLLMAdapter",
    "build_litellm_model_string",
]
