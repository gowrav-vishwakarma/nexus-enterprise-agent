"""Data models for multi-agent execution results."""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

from nexus.runner.result import AgentRunResult


class AgentGroupResult(BaseModel):
    """Result of orchestrating a group of agents."""

    group_name: str = Field(..., description="Name of the agent group executed")
    final_response: Optional[str] = Field(None, description="Aggregated final response")
    member_results: dict[str, Any] = Field(
        default_factory=dict,
        description="Results of member agents or subgroups (maps member name -> result)"
    )
    turns_used: int = Field(default=0, description="Total turns executed across members")
    total_tokens_in: int = Field(default=0, description="Total prompt tokens used by all members")
    total_tokens_out: int = Field(default=0, description="Total completion tokens used by all members")
    total_tokens_saved_by_rcs: int = Field(default=0, description="Total tokens saved by RCS across members")
    duration_ms: int = Field(default=0, description="Total execution time in milliseconds")
    status: Literal["completed", "failed", "interrupted"] = Field(
        default="completed", description="Terminal status of group execution"
    )
    error: Optional[str] = Field(None, description="Error message if group failed")
