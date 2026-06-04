"""RunContext - dependency injection for tools."""

from typing import Any, Optional

from pydantic import BaseModel


class RunContext(BaseModel):
    """Context injected into tool calls for dependency injection.
    
    Provides access to per-request services like database connections,
    user info, session data, etc.
    """
    
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    metadata: dict[str, Any] = {}
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from metadata."""
        return self.metadata.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a value in metadata."""
        self.metadata[key] = value
