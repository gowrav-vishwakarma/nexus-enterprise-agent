"""Session storage configuration models."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from nexus.storage.paths import get_data_root


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

    data_root: str = Field(
        default_factory=lambda: str(get_data_root()),
        description="Tenant storage root (default ./tenants, override via NEXUS_DATA_ROOT)",
    )
    tenant_scoped: bool = Field(
        default=True,
        description="Store sessions under tenants/{tenant_id}/users/{user_id}/{session_id}/",
    )
    base_path: str = Field(
        default="./nexus_sessions",
        description="Legacy flat base directory when tenant_scoped=False",
    )
    filename_template: str = Field(default="{session_id}.json", description="Filename template")
    overwrite_mode: Literal["full_rewrite", "append_jsonl"] = Field(
        default="full_rewrite", description="Write mode"
    )
    pretty_print: bool = Field(default=False, description="Pretty-print JSON")
    compression: Optional[Literal["gzip"]] = Field(None, description="Compression type")

    def to_adapter_config(self) -> dict[str, Any]:
        return {
            "data_root": self.data_root,
            "tenant_scoped": self.tenant_scoped,
            "base_path": self.base_path,
            "filename_template": self.filename_template,
            "overwrite_mode": self.overwrite_mode,
            "pretty_print": self.pretty_print,
        }


class SQLiteStorageConfig(BaseModel):
    """SQLite storage configuration."""

    data_root: str = Field(
        default_factory=lambda: str(get_data_root()),
        description="Tenant storage root (default ./tenants, override via NEXUS_DATA_ROOT)",
    )
    tenant_scoped: bool = Field(
        default=True,
        description="Store sessions in tenants/{tenant_id}/users/{user_id}/sessions.db",
    )
    db_path: Optional[str] = Field(
        default=None,
        description="Single shared database path when tenant_scoped=False",
    )
    table_prefix: str = Field(default="nexus_", description="Table name prefix")
    wal_mode: bool = Field(default=True, description="Enable WAL mode")
    auto_migrate: bool = Field(default=True, description="Auto-create tables")

    def to_adapter_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "data_root": self.data_root,
            "tenant_scoped": self.tenant_scoped,
            "table_prefix": self.table_prefix,
            "wal_mode": self.wal_mode,
            "auto_migrate": self.auto_migrate,
        }
        if self.db_path is not None:
            config["db_path"] = self.db_path
        return config


class PostgreSQLStorageConfig(BaseModel):
    """PostgreSQL storage configuration."""

    model_config = ConfigDict(populate_by_name=True)

    dsn: SecretStr = Field(..., description="Database connection string")
    pool_size: int = Field(default=10, ge=1, description="Connection pool size")
    max_overflow: int = Field(default=20, ge=0, description="Max overflow connections")
    db_schema: str = Field(
        default="public",
        description="Database schema",
        alias="schema",
    )
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
