"""Lazy database connection/session management for PostgreSQL and tests."""

from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPOSITORY_ROOT / ".env", override=False)


class DatabaseNotConfigured(RuntimeError):
    """Raised when a database-backed operation is requested without DATABASE_URL."""


def get_database_url() -> str | None:
    value = os.getenv("DATABASE_URL", "").strip()
    return value or None


@lru_cache(maxsize=8)
def _engine_for_url(database_url: str) -> Engine:
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
    )
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def get_engine() -> Engine:
    database_url = get_database_url()
    if not database_url:
        raise DatabaseNotConfigured(
            "DATABASE_URL is not configured. Copy .env.example to .env and configure PostgreSQL."
        )
    return _engine_for_url(database_url)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a session, roll back failures, and always close it."""
    with Session(get_engine()) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


def get_db_session() -> Iterator[Session]:
    """FastAPI dependency with rollback on request errors and guaranteed cleanup."""
    try:
        engine = get_engine()
    except DatabaseNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    with Session(engine) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


def check_database_connection() -> bool:
    """Return true only when the configured database answers SELECT 1."""
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    return True
