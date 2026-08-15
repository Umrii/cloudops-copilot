"""Database access: a small connection pool over psycopg3 with pgvector wired in.

We deliberately use raw SQL rather than an ORM so the vector-search query stays
explicit and easy to explain — the cosine-distance operator (<=>) is the heart
of retrieval and shouldn't be hidden behind an abstraction.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_pool: ConnectionPool | None = None


def _configure(conn: psycopg.Connection) -> None:
    """Runs for every pooled connection: enable the vector type adapter."""
    register_vector(conn)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=10,
            configure=_configure,
            open=True,
            kwargs={"autocommit": True},
        )
    return _pool


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Borrow a connection from the pool."""
    with get_pool().connection() as conn:
        yield conn


def init_db() -> None:
    """Ensure the extension, tables and indexes exist. Idempotent.

    The vector extension must be created before register_vector can adapt the
    type, so this runs on a fresh connection outside the configured pool.
    """
    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute(ddl)
    logger.info("Database schema ensured.")


def healthcheck() -> bool:
    """Return True if the database answers a trivial query."""
    try:
        with get_pool().connection(timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as exc:  # noqa: BLE001 - health endpoint reports, never raises
        logger.warning("Database healthcheck failed: %s", exc)
        return False


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
