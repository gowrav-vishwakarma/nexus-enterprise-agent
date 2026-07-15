"""Session storage configuration models."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from nexus.storage.paths import get_data_root


StorageAdapterType = Literal["memory", "file", "sqlite", "postgresql", "redis", "custom"]
SchemaMode = Literal["managed", "existing", "qualified"]


class SessionStorageConfig(BaseModel):
    """Configuration for session persistence."""

    adapter: StorageAdapterType = Field(
        default="memory", description="Storage backend to use"
    )
    adapter_config: dict[str, Any] = Field(
        default_factory=dict, description="Adapter-specific configuration"
    )
    custom_adapter_class: Optional[str] = Field(
        default=None,
        description="Import path for custom StorageAdapter when adapter='custom'",
    )
    custom_memory_adapter_class: Optional[str] = Field(
        default=None,
        description=(
            "Import path for a custom CrossSessionMemoryStore. "
            "When set, PersistenceFactory uses it instead of the built-in "
            "memory store for the chosen adapter (or whenever you want a "
            "product-specific memory backend)."
        ),
    )
    codec_class: Optional[str] = Field(
        default=None,
        description=(
            "Import path for a SessionCodec. Default uses DefaultSessionCodec "
            "(canonical AgentSession JSON)."
        ),
    )


class MemoryStorageConfig(BaseModel):
    """In-memory storage configuration."""

    max_sessions: int = Field(default=10000, ge=1, description="Max sessions (LRU eviction)")
    ttl_seconds: Optional[int] = Field(None, description="Session TTL in seconds")

    def to_adapter_config(self) -> dict[str, Any]:
        return {"max_sessions": self.max_sessions, "ttl_seconds": self.ttl_seconds}


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
    db_schema: Optional[str] = Field(
        default=None,
        description="Database schema; None uses connection default",
        alias="schema",
    )
    schema_mode: SchemaMode = Field(
        default="managed",
        description="managed=optional DDL; existing=never DDL; qualified=schema.table SQL",
    )
    sessions_table: Optional[str] = Field(
        default=None,
        description="Override sessions table, e.g. acme.agent_sessions",
    )
    user_memory_table: Optional[str] = Field(
        default=None,
        description="Override cross-session memory table",
    )
    table_prefix: str = Field(default="nexus_", description="Table name prefix")
    auto_migrate: bool = Field(
        default=False,
        description="Auto-create tables when schema_mode=managed",
    )
    connect_args: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra asyncpg pool kwargs (SSL, server_settings, etc.)",
    )

    def to_adapter_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "dsn": self.dsn.get_secret_value(),
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "schema_mode": self.schema_mode,
            "table_prefix": self.table_prefix,
            "auto_migrate": self.auto_migrate,
            "connect_args": self.connect_args,
        }
        if self.db_schema is not None:
            config["schema"] = self.db_schema
        if self.sessions_table is not None:
            config["sessions_table"] = self.sessions_table
        if self.user_memory_table is not None:
            config["user_memory_table"] = self.user_memory_table
        return config


class RedisStorageConfig(BaseModel):
    """Redis storage configuration."""

    url: Optional[str] = Field(
        default=None,
        description="Full Redis URL (overrides host/port/password/db)",
    )
    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, ge=1, description="Redis port")
    db: int = Field(default=0, ge=0, description="Redis database number")
    password: Optional[SecretStr] = Field(None, description="Redis password")
    key_prefix: str = Field(default="nexus:", description="Key prefix")
    session_key_template: Optional[str] = Field(
        default=None,
        description='Session key template, e.g. "{prefix}session:{session_id}"',
    )
    index_key_template: Optional[str] = Field(
        default=None,
        description='Index ZSET template, e.g. "{prefix}idx:{tenant}:{user}"',
    )
    memory_key_template: Optional[str] = Field(
        default=None,
        description='Cross-session memory key template, e.g. "{prefix}xmem:{memory_key}"',
    )
    ttl_seconds: Optional[int] = Field(None, description="Default TTL for sessions")
    max_connections: int = Field(default=50, ge=1, description="Connection pool size")

    def to_adapter_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "db": self.db,
            "key_prefix": self.key_prefix,
            "ttl_seconds": self.ttl_seconds,
            "max_connections": self.max_connections,
        }
        if self.url:
            config["url"] = self.url
        if self.password is not None:
            config["password"] = self.password.get_secret_value()
        if self.session_key_template:
            config["session_key_template"] = self.session_key_template
        if self.index_key_template:
            config["index_key_template"] = self.index_key_template
        if self.memory_key_template:
            config["memory_key_template"] = self.memory_key_template
        return config
