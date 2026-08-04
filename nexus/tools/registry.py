"""Tool registry to manage and execute tools."""

import asyncio
import inspect
import logging
import types
from collections.abc import Iterable
from typing import Any, Callable, Optional, Union, get_args, get_origin, get_type_hints

from pydantic import create_model

from nexus.config.rcs import RuntimeContextSummarizerConfig
from nexus.errors import ToolTimeoutError
from nexus.tools.context import RunContext
from nexus.tools.schema_injector import RCSSchemaInjector
from nexus.tools.toolsets import (
    Toolset,
    ToolsetCatalog,
    list_frontend_toolsets,
    resolve_toolset_tools,
)

logger = logging.getLogger(__name__)

_RUN_CONTEXT_PARAM_NAMES = frozenset({"ctx", "run_context"})


class ToolRegistry:
    """Registry to register and execute tools and plugins."""

    def __init__(self):
        # Maps "plugin_name.tool_name" -> (callable, parent_instance_or_none)
        self._tools: dict[str, tuple[Callable[..., Any], Optional[Any]]] = {}
        # Maps "plugin_name.tool_name" -> tool properties dict (from decorators)
        self._tool_metadata: dict[str, dict[str, Any]] = {}
        # Maps toolset name -> Toolset (named bundles owned by this registry)
        self._toolsets: dict[str, Toolset] = {}

    def register_plugin(self, plugin: Any) -> None:
        """Register a plugin class or instance.

        Scans the plugin for methods decorated with `@tool`.
        """
        # Determine namespace
        plugin_name = getattr(plugin, "_plugin_name", None)
        if not plugin_name:
            if hasattr(plugin, "__class__") and getattr(plugin.__class__, "_nexus_plugin", False):
                plugin_name = getattr(plugin.__class__, "_plugin_name", None)
            else:
                plugin_name = plugin.__class__.__name__.lower()
                if plugin_name.endswith("plugin"):
                    plugin_name = plugin_name[:-6]

        # Scan all methods/attributes
        for name in dir(plugin):
            val = getattr(plugin, name)
            if hasattr(val, "_nexus_tool"):
                tool_name = getattr(val, "_tool_name", name)
                full_name = f"{plugin_name}.{tool_name}"
                
                self._tools[full_name] = (val, plugin)
                self._tool_metadata[full_name] = {
                    "name": tool_name,
                    "full_name": full_name,
                    "description": getattr(val, "_tool_description", ""),
                    "tags": getattr(val, "_tool_tags", []),
                    "requires_approval": getattr(val, "_tool_requires_approval", False),
                    "timeout_seconds": getattr(val, "_tool_timeout_seconds", None),
                    "execution": getattr(val, "_tool_execution", "server"),
                    "plugin": plugin_name,
                }
                logger.info("Registered tool: %s", full_name)

    @staticmethod
    def _is_nexus_tool(obj: Any) -> bool:
        return callable(obj) and getattr(obj, "_nexus_tool", False)

    def _register_tool_flat(self, func: Callable[..., Any]) -> str:
        """Register *func* with a flat name and return that registry key."""
        if not self._is_nexus_tool(func):
            raise TypeError(
                f"Expected an @tool-decorated callable, got {type(func).__name__!r}"
            )
        self.register_tool(func, plugin_name=None)
        return getattr(func, "_tool_name", func.__name__)

    def add_tool(self, func: Callable[..., Any]) -> str:
        """Register a standalone @tool with a flat name (no plugin prefix)."""
        return self._register_tool_flat(func)

    def register_tool(
        self,
        func: Callable[..., Any],
        plugin_name: Optional[str] = "global",
    ) -> None:
        """Register a single standalone function as a tool.

        Pass ``plugin_name=""`` or ``None`` to expose a flat tool name
        (e.g. ``execute_sql``) instead of ``global.execute_sql``. Flat names
        are useful when a product frontend/prompt already expects unprefixed
        tool identifiers.
        """
        tool_name = getattr(func, "_tool_name", func.__name__)
        if plugin_name:
            full_name = f"{plugin_name}.{tool_name}"
            plugin_meta = plugin_name
        else:
            full_name = tool_name
            plugin_meta = ""

        self._tools[full_name] = (func, None)
        self._tool_metadata[full_name] = {
            "name": tool_name,
            "full_name": full_name,
            "description": getattr(func, "_tool_description", func.__doc__ or ""),
            "tags": getattr(func, "_tool_tags", []),
            "requires_approval": getattr(func, "_tool_requires_approval", False),
            "timeout_seconds": getattr(func, "_tool_timeout_seconds", None),
            "execution": getattr(func, "_tool_execution", "server"),
            "plugin": plugin_meta,
        }
        logger.info("Registered standalone tool: %s", full_name)

    def has(self, full_name: str) -> bool:
        """Return whether *full_name* is registered."""
        return full_name in self._tools

    def tool_names(self) -> list[str]:
        """Return all registered tool names (sorted)."""
        return sorted(self._tools.keys())

    def get_tool(self, full_name: str) -> tuple[Callable[..., Any], Optional[Any]]:
        """Return ``(callable, parent_instance)`` for a registered tool."""
        if full_name not in self._tools:
            raise KeyError(f"Tool '{full_name}' not found in registry")
        return self._tools[full_name]

    def count(self) -> int:
        """Number of registered tools."""
        return len(self._tools)

    # ------------------------------------------------------------------
    # Toolsets (named bundles owned by this registry)
    # ------------------------------------------------------------------
    def _coerce_toolset_tool_names(self, tools: Iterable[Any]) -> list[str]:
        """Turn toolset entries (strings or @tool callables) into registry keys."""
        names: list[str] = []
        for item in tools:
            if isinstance(item, str):
                names.append(item)
            elif self._is_nexus_tool(item):
                names.append(self._register_tool_flat(item))
            else:
                raise TypeError(
                    "Toolset tools must be registered tool name strings or "
                    f"@tool callables, got {type(item).__name__!r}"
                )
        return names

    def add_toolset(
        self,
        name: str,
        tools: Iterable[Any] = (),
        *,
        includes: Iterable[str] = (),
        description: str = "",
        visibility: str = "hidden",
        default_enabled: bool = False,
    ) -> Toolset:
        """Define a toolset and register any @tool callables in *tools*."""
        tool_names = self._coerce_toolset_tool_names(tools)
        return self.define_toolset(
            name,
            tool_names,
            includes=includes,
            description=description,
            visibility=visibility,
            default_enabled=default_enabled,
        )

    def define_toolset(
        self,
        name: str,
        tools: Iterable[str] = (),
        *,
        includes: Iterable[str] = (),
        description: str = "",
        visibility: str = "hidden",
        default_enabled: bool = False,
    ) -> Toolset:
        """Define a named toolset on this registry.

        Validates that every tool in *tools* is registered and every entry in
        *includes* is an already-defined toolset (define children first), so a
        bad reference fails immediately at define time rather than at runtime.
        """
        tools = list(tools)
        includes = list(includes)

        missing_tools = [t for t in tools if not self.has(t)]
        if missing_tools:
            raise ValueError(
                f"Toolset '{name}' references tools not in registry: "
                + ", ".join(sorted(missing_tools))
            )
        missing_includes = [c for c in includes if c not in self._toolsets]
        if missing_includes:
            raise ValueError(
                f"Toolset '{name}' includes undefined toolsets (define them first): "
                + ", ".join(sorted(missing_includes))
            )

        ts = Toolset(
            name=name,
            description=description,
            visibility=visibility,
            default_enabled=default_enabled,
            includes=includes,
            tools=tools,
        )
        self._toolsets[name] = ts
        return ts

    def get_toolset(self, name: str) -> Toolset:
        """Return the :class:`Toolset` registered under *name*."""
        if name not in self._toolsets:
            raise KeyError(f"Toolset '{name}' not found in registry")
        return self._toolsets[name]

    def has_toolset(self, name: str) -> bool:
        """Return whether a toolset named *name* is defined."""
        return name in self._toolsets

    def list_toolsets(self) -> list[Toolset]:
        """Return all defined toolsets."""
        return list(self._toolsets.values())

    def list_frontend_toolsets(
        self, tool_descriptions: Optional[dict[str, str]] = None
    ) -> list[ToolsetCatalog]:
        """Build the catalog of frontend-visible toolsets for product UIs."""
        return list_frontend_toolsets(
            self._toolsets, tool_descriptions=tool_descriptions
        )

    def resolve_toolset(self, name_or_names: Union[str, Iterable[str], None]) -> Optional[set[str]]:
        """Expand a toolset name (or list of names) into concrete tool names.

        Returns ``None`` when *name_or_names* is ``None`` (meaning "no toolset
        restriction"). Dotted names that are not defined toolsets resolve to
        themselves (treated as explicit tool names).
        """
        if name_or_names is None:
            return None
        if isinstance(name_or_names, str):
            names: list[str] = [name_or_names]
        else:
            names = list(name_or_names)
        out: set[str] = set()
        for name in names:
            out |= resolve_toolset_tools(name, self._toolsets)
        return out

    def schemas_for(self, names: Iterable[str]) -> list[dict[str, Any]]:
        """Return LLM tool schema dicts for the given names (preserves *names* order)."""
        by_name = {s["name"]: s for s in self.get_tool_schemas_for_llm()}
        return [by_name[n] for n in names if n in by_name]

    def discover_package(
        self,
        package_name: str,
        *,
        plugin_name: Optional[str] = None,
        skip: Iterable[str] = (),
    ) -> "ToolRegistry":
        """Import submodules of *package_name* and register every @tool."""
        from nexus.tools.discovery import register_tools

        register_tools(
            self,
            package_name,
            plugin_name=plugin_name,
            skip=skip,
        )
        return self

    def _is_run_context_type(self, annotation: Any) -> bool:
        if annotation is RunContext:
            return True
        if getattr(annotation, "__name__", None) == "RunContext":
            return True
        origin = get_origin(annotation)
        if origin is Union or origin is types.UnionType:
            return any(
                self._is_run_context_type(a)
                for a in get_args(annotation)
                if a is not type(None)
            )
        return False

    def _is_run_context_param(self, param_name: str, annotation: Any) -> bool:
        return (
            self._is_run_context_type(annotation)
            or param_name in _RUN_CONTEXT_PARAM_NAMES
        )

    def _get_function_schema(self, func: Callable[..., Any]) -> dict[str, Any]:
        """Generate JSON Schema for a function's parameters using Pydantic."""
        sig = inspect.signature(func)
        try:
            hints = get_type_hints(func, include_extras=True)
        except Exception:
            hints = {}
        fields: dict[str, Any] = {}

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            annotation = hints.get(param_name, param.annotation)
            if annotation is inspect.Parameter.empty:
                annotation = Any

            if self._is_run_context_param(param_name, annotation):
                continue

            default = ...
            if param.default != inspect.Parameter.empty:
                default = param.default

            fields[param_name] = (annotation, default)

        if not fields:
            return {"type": "object", "properties": {}, "required": []}

        DynamicModel = create_model(f"{func.__name__}_parameters", **fields)
        schema = DynamicModel.model_json_schema()
        schema.pop("title", None)
        return schema

    def get_tool_schemas_for_llm(
        self,
        plugin_names: Optional[list[str]] = None,
        rcs_config: Optional[RuntimeContextSummarizerConfig] = None,
    ) -> list[dict[str, Any]]:
        """Get the tool schemas in format expected by LLM providers.

        If rcs_config is enabled, injects the `_context_updates` property into
        every tool's parameters.
        """
        schemas = []
        for full_name, (func, _) in self._tools.items():
            metadata = self._tool_metadata[full_name]
            # Filter by plugin if provided. Flat tools (plugin="") are not
            # namespaced — they are allow-listed via toolsets instead, so keep them.
            if (
                plugin_names
                and metadata["plugin"]
                and metadata["plugin"] not in plugin_names
            ):
                continue

            params_schema = self._get_function_schema(func)

            # RCS Injection: inject _context_updates as an optional parameter
            if rcs_config and rcs_config.enabled:
                params_schema = RCSSchemaInjector.inject(params_schema, rcs_config)

            schema = {
                "name": full_name,
                "description": metadata["description"],
                "parameters": params_schema,
            }
            schemas.append(schema)

        return schemas

    def get_execution_mode(self, full_name: str) -> str:
        """Return ``server`` or ``client`` for a registered tool."""
        meta = self._tool_metadata.get(full_name) or {}
        return meta.get("execution", "server")

    def resolve_tool_name(self, name: str) -> str:
        """Map bare, flat, or legacy namespaced names to a registry key."""
        if self.has(name):
            return name
        for prefix in ("tenant.", "admin."):
            if name.startswith(prefix):
                bare = name.split(".", 1)[1]
                if self.has(bare):
                    return bare
        if "." not in name:
            for qualified in (f"tenant.{name}", f"admin.{name}"):
                if self.has(qualified):
                    return qualified
        raise ValueError(f"Tool '{name}' not found in registry")

    async def execute_tool(
        self,
        name: str,
        args: dict[str, Any],
        run_context: RunContext,
    ) -> Any:
        """Execute a tool by flat or legacy namespaced *name*."""
        full_name = self.resolve_tool_name(name)
        if full_name in self._tools:
            return await self.execute(full_name, "", args, run_context)
        plugin, _, tool = full_name.partition(".")
        return await self.execute(plugin, tool, args, run_context)

    def get_tool_metadata(self, full_name: str) -> dict[str, Any]:
        """Return metadata dict for a registered tool."""
        return dict(self._tool_metadata.get(full_name) or {})

    def requires_approval(self, full_name: str) -> bool:
        """Return whether the tool requires human approval before execution."""
        return bool(self.get_tool_metadata(full_name).get("requires_approval"))

    def get_timeout_seconds(self, full_name: str) -> Optional[int]:
        """Return the tool's declared timeout, or None when it declared none."""
        declared = self.get_tool_metadata(full_name).get("timeout_seconds")
        return int(declared) if declared else None

    async def execute(
        self,
        plugin: str,
        tool: str,
        args: dict[str, Any],
        run_context: RunContext,
    ) -> Any:
        """Execute a registered tool by its plugin name and tool name."""
        full_name = f"{plugin}.{tool}"
        if full_name not in self._tools:
            # Fallback check for single tool with no dots or matching plugin
            if tool == "" and plugin in self._tools:
                full_name = plugin
            else:
                raise ValueError(f"Tool '{full_name}' not found in registry")

        func, _parent = self._tools[full_name]

        sig = inspect.signature(func)
        try:
            hints = get_type_hints(func, include_extras=True)
        except Exception:
            hints = {}
        call_args: dict[str, Any] = {}

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            annotation = hints.get(param_name, param.annotation)
            if self._is_run_context_param(param_name, annotation):
                call_args[param_name] = run_context
            elif param_name in args:
                call_args[param_name] = args[param_name]
            elif param.default != inspect.Parameter.empty:
                continue

        # Execute with optional timeout
        timeout = self.get_timeout_seconds(full_name)

        async def _run() -> Any:
            if inspect.iscoroutinefunction(func):
                return await func(**call_args)
            return func(**call_args)

        try:
            if timeout and timeout > 0:
                return await asyncio.wait_for(_run(), timeout=timeout)
            return await _run()
        except asyncio.TimeoutError as exc:
            raise ToolTimeoutError(
                f"Tool '{full_name}' timed out after {timeout}s",
                tool_name=full_name,
                cause=exc,
            ) from exc
        except Exception as e:
            logger.error("Error executing tool %s: %s", full_name, e)
            raise
