"""Tool registry to manage and execute tools."""

import inspect
import logging
from typing import Any, Callable, Optional, Type, Union

from pydantic import BaseModel, create_model

from nexus.config.rcs import RuntimeContextSummarizerConfig
from nexus.tools.context import RunContext
from nexus.tools.schema_injector import RCSSchemaInjector

logger = logging.getLogger(__name__)


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

    def register_tool(self, func: Callable[..., Any], plugin_name: str = "global") -> None:
        """Register a single standalone function as a tool."""
        tool_name = getattr(func, "_tool_name", func.__name__)
        full_name = f"{plugin_name}.{tool_name}"
        
        self._tools[full_name] = (func, None)
        self._tool_metadata[full_name] = {
            "name": tool_name,
            "full_name": full_name,
            "description": getattr(func, "_tool_description", func.__doc__ or ""),
            "tags": getattr(func, "_tool_tags", []),
            "requires_approval": getattr(func, "_tool_requires_approval", False),
            "timeout_seconds": getattr(func, "_tool_timeout_seconds", 30),
            "execution": getattr(func, "_tool_execution", "server"),
            "plugin": plugin_name,
        }
        logger.info("Registered standalone tool: %s", full_name)

    def _get_function_schema(self, func: Callable[..., Any]) -> dict[str, Any]:
        """Generate JSON Schema for a function's parameters using Pydantic."""
        sig = inspect.signature(func)
        fields = {}

        for param_name, param in sig.parameters.items():
            # Skip self, cls, and RunContext parameters
            if param_name in ("self", "cls"):
                continue
            if param.annotation == RunContext or (hasattr(param.annotation, "__name__") and param.annotation.__name__ == "RunContext"):
                continue

            # Determine type annotation and default value
            param_type: Any = Any
            if param.annotation != inspect.Parameter.empty:
                param_type = param.annotation
            
            default = ...
            if param.default != inspect.Parameter.empty:
                default = param.default

            fields[param_name] = (param_type, default)

        if not fields:
            return {"type": "object", "properties": {}, "required": []}

        # Create a dynamic Pydantic model
        DynamicModel = create_model(f"{func.__name__}_parameters", **fields)
        schema = DynamicModel.model_json_schema()
        
        # Clean up title/definitions in schema
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
            # Filter by plugin if provided
            if plugin_names and metadata["plugin"] not in plugin_names:
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

        func, parent = self._tools[full_name]
        
        # Prepare arguments
        sig = inspect.signature(func)
        call_args = {}

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            if param.annotation == RunContext or (hasattr(param.annotation, "__name__") and param.annotation.__name__ == "RunContext"):
                call_args[param_name] = run_context
            elif param_name in args:
                call_args[param_name] = args[param_name]
            elif param.default != inspect.Parameter.empty:
                # Use default value
                continue
            else:
                # Missing argument - might be optional or default, let python raise inspect.Parameter error if it fails
                pass

        # Execute
        try:
            if inspect.iscoroutinefunction(func):
                return await func(**call_args)
            else:
                # Run sync functions in thread pool if needed, or execute directly
                return func(**call_args)
        except Exception as e:
            logger.error("Error executing tool %s: %s", full_name, e)
            raise
