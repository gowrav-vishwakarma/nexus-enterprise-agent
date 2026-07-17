"""Decorators for registering tools and plugins."""

from typing import Any, Callable, Optional, TypeVar, Union

F = TypeVar("F", bound=Callable[..., Any])


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[list[str]] = None,
    requires_approval: bool = False,
    timeout_seconds: int = 30,
    execution: str = "server",
) -> Callable[[F], F]:
    """Decorator to register a function or method as an agent tool.

    Args:
        name: Optional custom name for the tool. Defaults to function name.
        description: Optional description. Defaults to function docstring.
        tags: Optional list of tags for metadata and filtering.
        requires_approval: Whether this tool requires human-in-the-loop approval.
        timeout_seconds: Maximum execution time in seconds.
        execution: ``server`` (default) or ``client`` — client tools pause the
            run and wait for ``AgentRunner.resume()`` with the tool result.
    """

    def decorator(func: F) -> F:
        func._nexus_tool = True
        func._tool_name = name or func.__name__
        func._tool_description = description or func.__doc__ or ""
        func._tool_tags = tags or []
        func._tool_requires_approval = requires_approval
        func._tool_timeout_seconds = timeout_seconds
        func._tool_execution = execution
        return func

    return decorator


def tool_plugin(name: str) -> Callable[[type], type]:
    """Decorator to designate a class as a tool plugin namespace.

    All methods in the class decorated with `@tool` will be namespaced
    under this plugin name (e.g., `plugin_name.tool_name`).

    Args:
        name: Unique namespace/name for this plugin.
    """

    def decorator(cls: type) -> type:
        cls._nexus_plugin = True
        cls._plugin_name = name
        return cls

    return decorator
