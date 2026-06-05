"""Resolve manifest documents into AgentConfig / AgentGroupConfig trees."""

from __future__ import annotations

import copy
import logging
from typing import Any, Union

from pydantic import SecretStr

from nexus.config.agent import AgentConfig, AgentGroupConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.orchestration.errors import (
    ManifestLoadError,
    MemberNotFoundError,
    ReferenceCycleError,
)
from nexus.orchestration.prompts import PromptValue, resolve_persona_config
from nexus.orchestration.schema import OrchestrationManifestSchema
from nexus.tools.context import RunContext

logger = logging.getLogger(__name__)

MemberConfig = Union[AgentConfig, AgentGroupConfig]

_UNIMPLEMENTED_PATTERNS = frozenset({"swarm"})


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge override into a copy of base."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ManifestResolver:
    """Convert a validated manifest into runtime AgentConfig / AgentGroupConfig."""

    def __init__(
        self,
        schema: OrchestrationManifestSchema,
        prompts: dict[str, PromptValue],
        run_context: RunContext,
    ) -> None:
        self.schema = schema
        self.prompts = prompts
        self.run_context = run_context

    def resolve_root(self) -> MemberConfig:
        """Resolve the manifest root agent or group."""
        return self._resolve_root_name(self.schema.root)

    def _resolve_root_name(self, name: str) -> MemberConfig:
        if name in self.schema.agents:
            return self._resolve_agent(name, self.schema.agents[name])
        if name in self.schema.groups:
            return self._resolve_group(name, self.schema.groups[name], resolving=[])
        raise ManifestLoadError(
            f"Root {name!r} not found in agents or groups. "
            f"Available agents: {sorted(self.schema.agents)}; "
            f"groups: {sorted(self.schema.groups)}"
        )

    def _resolve_agent(self, name: str, spec: dict[str, Any]) -> AgentConfig:
        merged = deep_merge(self.schema.defaults.agent, spec)
        merged["name"] = name

        if "llm" not in merged and self.schema.defaults.llm:
            merged["llm"] = copy.deepcopy(self.schema.defaults.llm)

        if "persona" in merged and isinstance(merged["persona"], dict):
            merged["persona"] = resolve_persona_config(
                merged["persona"],
                prompts=self.prompts,
                run_context=self.run_context,
            )

        llm_data = merged.get("llm")
        if isinstance(llm_data, dict):
            merged["llm"] = _coerce_llm_config(llm_data)

        return AgentConfig.model_validate(merged)

    def _resolve_group(
        self,
        name: str,
        spec: dict[str, Any],
        *,
        resolving: list[str],
    ) -> AgentGroupConfig:
        if name in resolving:
            cycle = resolving + [name]
            raise ReferenceCycleError(cycle)

        merged = deep_merge(self.schema.defaults.group, spec)
        merged["name"] = name

        pattern = merged.get("pattern", "supervisor")
        if pattern in _UNIMPLEMENTED_PATTERNS:
            logger.warning(
                "Group %r pattern %r is not implemented; falling back to pipeline",
                name,
                pattern,
            )
            merged["pattern"] = "pipeline"

        members_spec = merged.get("members", [])
        resolved_members: list[MemberConfig] = []
        stack = resolving + [name]

        for member_entry in members_spec:
            resolved_members.append(
                self._resolve_member_entry(member_entry, group_name=name, resolving=stack)
            )

        merged["members"] = resolved_members
        return AgentGroupConfig.model_validate(merged)

    def _resolve_member_entry(
        self,
        entry: Any,
        *,
        group_name: str,
        resolving: list[str],
    ) -> MemberConfig:
        if isinstance(entry, str):
            return self._resolve_member_ref(entry, group_name=group_name, resolving=resolving)

        if isinstance(entry, dict):
            if _is_inline_group(entry):
                inline_name = entry.get("name")
                if not inline_name:
                    raise ManifestLoadError(
                        f"Inline group in {group_name!r} must include a name"
                    )
                return self._resolve_group(inline_name, entry, resolving=resolving)
            inline_name = entry.get("name", f"{group_name}_member")
            return self._resolve_agent(inline_name, entry)

        raise ManifestLoadError(
            f"Invalid member entry in group {group_name!r}: expected name ref or mapping"
        )

    def _resolve_member_ref(
        self,
        name: str,
        *,
        group_name: str,
        resolving: list[str],
    ) -> MemberConfig:
        if name in self.schema.agents:
            return self._resolve_agent(name, self.schema.agents[name])
        if name in self.schema.groups:
            return self._resolve_group(
                name,
                self.schema.groups[name],
                resolving=resolving,
            )
        raise MemberNotFoundError(name, group_name)


def _is_inline_group(entry: dict[str, Any]) -> bool:
    return "pattern" in entry and "members" in entry


def _coerce_llm_config(data: dict[str, Any]) -> LLMProviderConfig:
    llm_data = dict(data)
    api_key = llm_data.get("api_key", "")
    if not isinstance(api_key, SecretStr):
        llm_data["api_key"] = SecretStr(str(api_key or ""))
    return LLMProviderConfig.model_validate(llm_data)
