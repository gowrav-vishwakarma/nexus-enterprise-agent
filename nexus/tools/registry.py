"""Tool registry to manage and execute tools."""

import inspect
import logging
import types
from typing import Any, Callable, Optional, Type, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel, create_model

from nexus.config.rcs import RuntimeContextSummarizerConfig
from nexus.tools.context import RunContext
from nexus.tools.schema_injector import RCSSchemaInjector

logger = logging.getLogger(__name__)

_RUN_CONTEXT_PARAM_NAMES = frozenset({"ctx", "run_context"})


class ToolRegistry:
    """Registry to register and execute tools and plugins."""

    def __init__(self):
        # Maps "plugin_name.tool_name" -> (callable, parent_instance_or_none)
        self._tools: dict[str, tuple[Callable[..., Any], Optional[Any]]] = {}
        # Maps "plugin_name.tool_name" -> tool properties dict (from decorators)
        self._tool_metadata: dict[str, dict[str, Any]] = {}

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
                    "timeout_seconds": getattr(val, "_tool_timeout_seconds", 30),
                    "execution": getattr(val, "_tool_execution", "server"),
                    "plugin": plugin_name,
                }
                logger.info("Registered tool: %s", full_name)

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
            "timeout_seconds": getattr(func, "_tool_timeout_seconds", 30),
            "execution": getattr(func, "_tool_execution", "server"),
            "plugin": plugin_meta,
        }
        logger.info("Registered standalone tool: %s", full_name)

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

        # Execute
        try:
            if inspect.iscoroutinefunction(func):
                return await func(**call_args)
            return func(**call_args)
        except Exception as e:
            logger.error("Error executing tool %s: %s", full_name, e)
            raise
