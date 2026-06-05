"""Import helpers for orchestration manifests."""

from __future__ import annotations

from importlib import import_module
from typing import Any


def import_from_path(class_path: str) -> Any:
    """Import and return an object from ``module.Class`` path."""
    module_path, _, class_name = class_path.rpartition(".")
    if not module_path or not class_name:
        raise ValueError(f"Invalid import path: {class_path!r}")
    module = import_module(module_path)
    return getattr(module, class_name)
