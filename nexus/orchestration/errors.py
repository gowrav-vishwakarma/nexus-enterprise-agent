"""Orchestration manifest and runtime errors."""


class OrchestrationError(Exception):
    """Base error for YAML orchestration bootstrap."""


class ManifestLoadError(OrchestrationError):
    """Failed to load or validate a manifest file."""


class PromptNotFoundError(OrchestrationError):
    """Referenced prompt name is missing from the prompts module PROMPTS dict."""

    def __init__(self, prompt_name: str, available: list[str]) -> None:
        self.prompt_name = prompt_name
        self.available = available
        keys = ", ".join(sorted(available)) if available else "(none)"
        super().__init__(
            f"Prompt {prompt_name!r} not found in PROMPTS registry. Available: {keys}"
        )


class ReferenceCycleError(OrchestrationError):
    """Circular reference detected while resolving group members."""

    def __init__(self, cycle_path: list[str]) -> None:
        self.cycle_path = cycle_path
        path = " -> ".join(cycle_path)
        super().__init__(f"Circular group reference detected: {path}")


class MemberNotFoundError(OrchestrationError):
    """Group member reference could not be resolved."""

    def __init__(self, name: str, group: str) -> None:
        super().__init__(f"Member {name!r} not found for group {group!r}")
