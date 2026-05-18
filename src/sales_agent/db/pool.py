"""asyncpg connection pool — module-level singleton.

Lifecycle:
- Web server (FastAPI lifespan) calls `connect()` on startup, `disconnect()` on shutdown.
- Discord bot calls the same in its `setup_hook` / `close`.
- Workers (Cloud Scheduler → Cloud Run job) call them around their handler.

Every connection is initialized with the pgvector adapter so `vector(1536)`
columns round-trip as Python lists of floats. `agent_memory.embedding` is
the only column that uses this today.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import asyncpg

from sales_agent.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Run-once-per-connection setup. Registers pgvector codecs."""
    try:
        # pgvector adapter — installed via the `pgvector` Python package.
        from pgvector.asyncpg import register_vector

        await register_vector(conn)
    except ImportError:
        logger.warning(
            "db.pool: pgvector adapter not installed — agent_memory.embedding "
            "writes will fail. pip install pgvector."
        )


async def connect(*, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    """Create the pool if not already created. Idempotent."""
    global _pool
    if _pool is not None:
        return _pool

    if not settings.postgres_rw_url:
        raise RuntimeError("POSTGRES_RW_URL not set")

    _pool = await asyncpg.create_pool(
        dsn=settings.postgres_rw_url,
        min_size=min_size,
        max_size=max_size,
        init=_init_connection,
    )
    logger.info("db.pool: connected (%d–%d connections)", min_size, max_size)
    return _pool


async def disconnect() -> None:
    """Close the pool. Idempotent."""
    global _pool
    if _pool is None:
        return
    await _pool.close()
    _pool = None
    logger.info("db.pool: disconnected")


def pool() -> asyncpg.Pool:
    """Return the live pool. Raises if `connect()` was not called first."""
    if _pool is None:
        raise RuntimeError("db.pool: connect() not called yet")
    return _pool
