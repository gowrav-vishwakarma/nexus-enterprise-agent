"""Session storage configuration models."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, SecretStr


StorageAdapterType = Literal["memory", "file", "sqlite", "postgresql", "redis"]


class SessionStorageConfig(BaseModel):
    """Configuration for session persistence."""

    adapter: StorageAdapterType = Field(
        default="memory", description="Storage backend to use"
    )
    adapter_config: dict[str, Any] = Field(
        default_factory=dict, description="Adapter-specific configuration"
    )


class MemoryStorageConfig(BaseModel):
    """In-memory storage configuration."""

    max_sessions: int = Field(default=10000, ge=1, description="Max sessions (LRU eviction)")
    ttl_seconds: Optional[int] = Field(None, description="Session TTL in seconds")


class FileStorageConfig(BaseModel):
    """File-based storage configuration."""

    base_path: str = Field(default="./nexus_sessions", description="Base directory for sessions")
    filename_template: str = Field(default="{session_id}.json", description="Filename template")
    overwrite_mode: Literal["full_rewrite", "append_jsonl"] = Field(
        default="full_rewrite", description="Write mode"
    )
    pretty_print: bool = Field(default=False, description="Pretty-print JSON")
    compression: Optional[Literal["gzip"]] = Field(None, description="Compression type")


class SQLiteStorageConfig(BaseModel):
    """SQLite storage configuration."""

    db_path: str = Field(default="./nexus_sessions.db", description="Database file path")
    table_prefix: str = Field(default="nexus_", description="Table name prefix")
    wal_mode: bool = Field(default=True, description="Enable WAL mode")
    auto_migrate: bool = Field(default=True, description="Auto-create tables")


class PostgreSQLStorageConfig(BaseModel):
    """PostgreSQL storage configuration."""

    dsn: SecretStr = Field(..., description="Database connection string")
    pool_size: int = Field(default=10, ge=1, description="Connection pool size")
    max_overflow: int = Field(default=20, ge=0, description="Max overflow connections")
    schema: str = Field(default="public", description="Database schema")
    table_prefix: str = Field(default="nexus_", description="Table name prefix")
    auto_migrate: bool = Field(default=True, description="Auto-create tables")


class RedisStorageConfig(BaseModel):
    """Redis storage configuration."""

    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, ge=1, description="Redis port")
    db: int = Field(default=0, ge=0, description="Redis database number")
    password: Optional[SecretStr] = Field(None, description="Redis password")
    key_prefix: str = Field(default="nexus:", description="Key prefix")
    ttl_seconds: Optional[int] = Field(None, description="Default TTL for sessions")
    max_connections: int = Field(default=50, ge=1, description="Connection pool size")
