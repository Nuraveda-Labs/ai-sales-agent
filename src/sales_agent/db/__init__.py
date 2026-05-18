"""Postgres access layer.

Owns the `sales_agent.*` schema (see `migrations/0001_init_schema.sql`).
Async access via asyncpg with a module-level pool singleton.

Public surface:
- `pool.connect() / pool.disconnect() / pool.pool()` — lifecycle.
- `models.*`  — Pydantic row + create models with Literal-typed enums.
- `repos.*`   — `LeadRepo`, `DraftRepo`, `SendRepo`, `EventRepo`,
                `UnsubRepo`, `MemoryRepo`.

Repos accept the asyncpg pool by constructor injection so tests can pass
a fixture pool and so multiple agents (this one, future product agents)
can share the same engine without globals leaking.
"""

from sales_agent.db import models, pool, repos
from sales_agent.db.repos import (
    DraftRepo,
    EventRepo,
    LeadRepo,
    MemoryRepo,
    SendRepo,
    UnsubRepo,
)

__all__ = [
    "DraftRepo",
    "EventRepo",
    "LeadRepo",
    "MemoryRepo",
    "SendRepo",
    "UnsubRepo",
    "models",
    "pool",
    "repos",
]
