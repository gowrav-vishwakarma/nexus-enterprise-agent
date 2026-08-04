# Scope primitive

Nexus uses one **scope model** for memory, skills, RAG collections, artifacts, caches, and quotas.

## Levels

| Level | Fields used |
|-------|-------------|
| `global` | none |
| `tenant` | `tenant_id` |
| `company` | `tenant_id`, `company_id` |
| `user` | `tenant_id`, `company_id`, `user_id` |

## API

```python
from nexus import RunContext, ScopeLevel, scope_key

ctx = RunContext(tenant_id="acme", user_id="u1")
key = scope_key(ctx, ScopeLevel.USER, "memory")
# tenant:acme:company:...:user:u1:memory
```

Skills and memory configs that declare `keys=["tenant_id", "user_id"]` use the same rules via `scope_keys_from_config()`.

## Missing fields never widen a scope

Every level emits its own segment even when the context left that field empty, using
`_` as a placeholder. A request with a tenant but no user gives:

```
scope_key(ctx, ScopeLevel.TENANT) -> "tenant:acme"
scope_key(ctx, ScopeLevel.USER)   -> "tenant:acme:company:_:user:_"
```

The two are different strings. If the narrower level collapsed onto the broader one,
a user-scoped write for an unidentified user would land in the bucket the whole
tenant reads.

## Sanitize before using a key as a path

`scope_key` builds an identifier, not a filesystem path. Scope values come from
request data, so a tenant id can contain `../`. Anything that turns a key into a path
must sanitize each segment with `sanitize_segment()` from
[nexus/storage/paths.py](../../nexus/storage/paths.py) and confirm the result stays
inside its root — `LocalArtifactStore` does both.

## Formats that predate this primitive

Two storage layouts encode scope themselves and are **deliberately not** rebuilt on
`scope_key`, because both are persisted formats and changing them would orphan live
data:

| Format | Shape | Where |
|--------|-------|-------|
| Session files | `tenants/{tenant}/users/{user}/{session}/` | [nexus/storage/paths.py](../../nexus/storage/paths.py) |
| Cross-session memory key | `{tenant}:{user}:{namespace}` | [nexus/memory/cross_session_store.py](../../nexus/memory/cross_session_store.py) |

Both are user-scoped in the sense above. The built-in memory stores ignore
`company_id` on purpose — memory belongs to a user within a tenant. A custom store
that needs company separation receives `company_id` on every call and can use it.
