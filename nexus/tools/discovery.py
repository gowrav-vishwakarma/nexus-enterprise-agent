"""Discover @tool modules in a package and register them on a ToolRegistry."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Iterable
from typing import Callable, Optional

from nexus.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def discover_tool_modules(package_name: str, *, skip: Iterable[str] = ()) -> list:
    """Import submodules of *package_name* (side-effect: loads @tool definitions)."""
    pkg = importlib.import_module(package_name)
    skip_set = set(skip)
    modules = []
    for _, name, _ in pkgutil.iter_modules(pkg.__path__):
        if name.startswith("_") or name in skip_set:
            continue
        full_name = f"{package_name}.{name}"
        try:
            modules.append(importlib.import_module(full_name))
            logger.debug("[discovery] discovered %s", full_name)
        except Exception as e:
            logger.warning("[discovery] failed importing %s: %s", full_name, e)
    return modules


def _iter_tool_callables(module) -> list[Callable]:
    out: list[Callable] = []
    for attr in dir(module):
        if attr.startswith("_"):
            continue
        val = getattr(module, attr, None)
        if callable(val) and getattr(val, "_nexus_tool", False):
            out.append(val)
    return out


def register_tools(
    registry: ToolRegistry,
    package_name: str,
    *,
    plugin_name: Optional[str] = None,
    skip: Iterable[str] = (),
) -> ToolRegistry:
    """Import *package_name* submodules and register every @tool found.

    When *plugin_name* is a non-empty string, tools are registered as
    ``plugin_name.tool_name``. When *plugin_name* is ``None`` or ``""``, tools
    use flat names (no prefix).
    """
    flat = not plugin_name
    namespace = "" if flat else plugin_name
    seen: set[str] = set()
    for mod in discover_tool_modules(package_name, skip=skip):
        for fn in _iter_tool_callables(mod):
            tool_name = getattr(fn, "_tool_name", fn.__name__)
            full_key = tool_name if flat else f"{namespace}.{tool_name}"
            if full_key in seen:
                logger.warning(
                    "[discovery] duplicate tool %s in %s — skipping",
                    full_key,
                    mod.__name__,
                )
                continue
            seen.add(full_key)
            registry.register_tool(fn, plugin_name=namespace or None)
    logger.info("[discovery] registered %d tools from %s", len(seen), package_name)
    return registry
