# app/database.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()


def _default_db_url() -> str:
    """
    Use a file-based SQLite DB at the project root when DATABASE_URL is not provided.
    File-based SQLite works reliably across async connections and threads.
    """
    root = Path(__file__).resolve().parents[1]
    return f"sqlite+aiosqlite:///{(root / 'test.db').as_posix()}"


# Robust DATABASE_URL handling


def _normalize_database_url(raw_url: Optional[str]) -> Optional[str]:
    """Ensure async-friendly drivers even if the URL omits them."""

    if not raw_url:
        return raw_url

    lowered = raw_url.lower()
    for prefix in ("postgresql+psycopg2://", "postgresql://", "postgres://"):
        if lowered.startswith(prefix):
            return "postgresql+asyncpg://" + raw_url.split("://", 1)[1]

    return raw_url


DEFAULT_SQLITE_URL: str = _default_db_url()
DATABASE_URL: str = _normalize_database_url(os.getenv("DATABASE_URL")) or DEFAULT_SQLITE_URL

# Optional echo flag for local debugging
ECHO = os.getenv("SQLALCHEMY_ECHO", "0").lower() in {"1", "true", "yes"}


def _build_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url,
        echo=ECHO,
        pool_pre_ping=True,
    )


def _build_session_factory(bind_engine: AsyncEngine) -> sessionmaker:
    return sessionmaker(
        bind=bind_engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


Base = declarative_base()

# Public globals that can be reconfigured at runtime.
engine: AsyncEngine
SessionLocal: sessionmaker
async_session: sessionmaker
CURRENT_DATABASE_URL: str


def configure_engine(database_url: str) -> None:
    """Configure the global engine/session factory pair.

    This indirection allows the application to swap databases at runtime
    (e.g. falling back to SQLite when a Postgres instance is unavailable).
    """

    global engine, SessionLocal, async_session, CURRENT_DATABASE_URL

    engine = _build_engine(database_url)
    SessionLocal = _build_session_factory(engine)
    async_session = SessionLocal
    CURRENT_DATABASE_URL = database_url


# Initialise globals using the preferred database URL.
configure_engine(DATABASE_URL)


async def get_db():
    """FastAPI dependency that yields an AsyncSession."""

    async with SessionLocal() as session:
        yield session
