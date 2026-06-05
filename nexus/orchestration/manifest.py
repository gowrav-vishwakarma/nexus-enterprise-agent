"""Load orchestration manifests from YAML and companion prompt modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from nexus.config.storage import SessionStorageConfig
from nexus.orchestration.env import interpolate_env
from nexus.orchestration.errors import ManifestLoadError
from nexus.orchestration.prompts import PromptValue, load_prompts_module
from nexus.orchestration.schema import OrchestrationManifestSchema


@dataclass(frozen=True)
class OrchestrationManifest:
    """Parsed manifest bundle (cacheable across requests)."""

    path: Path
    schema: OrchestrationManifestSchema
    prompts: dict[str, PromptValue]
    raw: dict[str, Any]

    @property
    def storage_config(self) -> SessionStorageConfig:
        return self.schema.storage

    @property
    def plugins(self) -> dict[str, str]:
        return self.schema.plugins

    @classmethod
    def load(cls, path: str | Path) -> OrchestrationManifest:
        """Load a YAML manifest and its companion prompts module."""
        manifest_path = Path(path).resolve()
        if not manifest_path.is_file():
            raise ManifestLoadError(f"Manifest not found: {manifest_path}")

        raw_text = manifest_path.read_text(encoding="utf-8")
        try:
            raw_data = yaml.safe_load(raw_text) or {}
        except yaml.YAMLError as exc:
            raise ManifestLoadError(f"Invalid YAML in {manifest_path}: {exc}") from exc

        if not isinstance(raw_data, dict):
            raise ManifestLoadError(f"Manifest root must be a mapping: {manifest_path}")

        expanded = interpolate_env(raw_data)
        try:
            schema = OrchestrationManifestSchema.model_validate(expanded)
        except Exception as exc:
            raise ManifestLoadError(f"Invalid manifest schema in {manifest_path}: {exc}") from exc

        prompts_path = _resolve_prompts_path(manifest_path, schema.prompts_module)
        prompts = load_prompts_module(prompts_path)

        _validate_root(schema)
        return cls(path=manifest_path, schema=schema, prompts=prompts, raw=expanded)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        path: str | Path | None = None,
        prompts: dict[str, PromptValue] | None = None,
    ) -> OrchestrationManifest:
        """Build a manifest from an in-memory dict (primarily for tests)."""
        expanded = interpolate_env(data)
        schema = OrchestrationManifestSchema.model_validate(expanded)
        _validate_root(schema)
        manifest_path = Path(path).resolve() if path else Path("manifest.yaml")
        prompt_registry = prompts if prompts is not None else {}
        return cls(path=manifest_path, schema=schema, prompts=prompt_registry, raw=expanded)


def _resolve_prompts_path(manifest_path: Path, prompts_module: str | None) -> Path:
    if prompts_module:
        candidate = (manifest_path.parent / prompts_module).resolve()
        return candidate
    default_name = f"{manifest_path.stem}_prompts.py"
    return (manifest_path.parent / default_name).resolve()


def _validate_root(schema: OrchestrationManifestSchema) -> None:
    if schema.root not in schema.agents and schema.root not in schema.groups:
        raise ManifestLoadError(
            f"Root {schema.root!r} not found in agents or groups. "
            f"Available agents: {sorted(schema.agents)}; groups: {sorted(schema.groups)}"
        )
