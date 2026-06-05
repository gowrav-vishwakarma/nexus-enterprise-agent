# Per-tenant storage resolver

**Who this is for:** SaaS developers who need different databases or schemas per customer.

## Key terms

- **Persistence** — How and where Nexus saves session data and cross-chat memory.
- **Resolver** — Your class that picks storage settings per tenant and user.
- **Bundle** — Session manager + cross-session store wired together.

## When to use

Use a `PersistenceResolver` when:

- Enterprise customers bring their own database
- Free tier uses SQLite and paid tier uses PostgreSQL
- You cannot use one global `storage_config` for all tenants

## Protocol

Implement two methods:

| Method | What it returns |
|--------|-----------------|
| `resolve_storage_config(tenant_id, user_id)` | `SessionStorageConfig` for this tenant |
| `resolve_bundle(tenant_id, user_id)` | Optional full `PersistenceBundle` (or `None` to use storage config only) |

## Example skeleton

```python
from nexus.persistence import PersistenceFactory, PersistenceResolver
from nexus.config.storage import SessionStorageConfig

class MyResolver(PersistenceResolver):
    def resolve_storage_config(self, tenant_id, user_id):
        tenant = load_tenant(tenant_id)  # your database
        return SessionStorageConfig(
            adapter="postgresql",
            adapter_config={
                "dsn": tenant.db_dsn,
                "schema": tenant.db_schema,
                "schema_mode": "qualified",
                "auto_migrate": False,
            },
        )

    def resolve_bundle(self, tenant_id, user_id):
        return None

bundle = PersistenceFactory.from_resolver(MyResolver(), tenant_id="acme", user_id="u1")
```

Pass to orchestration:

```python
OrchestrationRuntime.from_manifest(manifest, run_context=ctx, persistence_resolver=MyResolver())
```

Or use `PersistenceFactory.from_storage_config()` for a single global backend.

## PostgreSQL notes

- `schema_mode: existing` — you own DDL; Nexus never creates tables
- `auto_migrate` defaults to **false** in production
- See [storage reference](../reference/storage.md)

## Next steps

- [SaaS example](saas-example.md)
- [Environment variables](../reference/environment.md)
