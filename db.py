"""
Shared Postgres connection pool for assessment-tool and socratic-tutor.

Both apps import get_conn() / put_conn() via this module.
The DATABASE_URL env var must be set before first import.

Usage:
    from db import get_conn, put_conn

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ...")
            rows = cur.fetchall()
        conn.commit()
    finally:
        put_conn(conn)

Or use the context manager helper:
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ...")
"""

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

_pool: ThreadedConnectionPool | None = None


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        url = os.environ.get('DATABASE_URL')
        if not url:
            raise RuntimeError('DATABASE_URL environment variable is not set')
        _pool = ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            dsn=url,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return _pool


def get_conn() -> psycopg2.extensions.connection:
    return _get_pool().getconn()


def put_conn(conn: psycopg2.extensions.connection) -> None:
    _get_pool().putconn(conn)


@contextmanager
def db_conn():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)
