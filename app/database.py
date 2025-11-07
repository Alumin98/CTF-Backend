# app/database.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.engine import URL
from sqlalchemy.engine.url import make_url

load_dotenv()


def _default_db_url() -> str:
    """
    Use a file-based SQLite DB at the project root when DATABASE_URL is not provided.
    File-based SQLite works reliably across async connections and threads.
    """
    root = Path(__file__).resolve().parents[1]
    return f"sqlite+aiosqlite:///{(root / 'test.db').as_posix()}"


# Robust DATABASE_URL handling


def _translate_sslmode(value: str) -> Optional[str]:
    """Translate libpq sslmode values to asyncpg-compatible flags."""

    normalized = value.strip().lower()
    if normalized in {"require", "verify-ca", "verify-full"}:
        return "true"
    if normalized == "disable":
        return "false"

    # Values like "prefer" and "allow" don't have asyncpg equivalents. Fall back to
    # driver defaults by omitting the parameter entirely.
    return None


def _normalize_database_url(raw_url: Optional[str]) -> Optional[str]:
    """Ensure async-friendly drivers even if the URL omits them."""

    if not raw_url:
        return raw_url

    try:
        url = make_url(raw_url)
    except Exception:
        # If SQLAlchemy can't parse the URL, fall back to the raw value.
        return raw_url

    driver = url.drivername.lower()
    if driver in {"postgresql", "postgres", "postgresql+psycopg2"}:
        url = url.set(drivername="postgresql+asyncpg")
    elif driver.startswith("postgresql+") and driver != "postgresql+asyncpg":
        url = url.set(drivername="postgresql+asyncpg")

    if url.drivername == "postgresql+asyncpg":
        query = dict(url.query)
        sslmode = query.pop("sslmode", None)
        if sslmode is not None:
            translated = _translate_sslmode(sslmode)
            if translated is not None:
                query["ssl"] = translated
        if query != url.query:
            url = url.set(query=query)

    return str(url)


def _railway_env_database_url(env: Mapping[str, str]) -> Optional[str]:
    """Construct a Postgres URL from Railway-provided PG* env vars."""

    host = env.get("PGHOST")
    database = env.get("PGDATABASE")
    user = env.get("PGUSER")

    if not (host and database and user):
        return None

    port = env.get("PGPORT")
    password = env.get("PGPASSWORD") or None

    query: dict[str, str] = {}
    sslmode = env.get("PGSSLMODE")
    if sslmode:
        translated = _translate_sslmode(sslmode)
        if translated is not None:
            query["ssl"] = translated

    try:
        port_value = int(port) if port is not None else None
    except (TypeError, ValueError):
        port_value = None

    return str(
        URL.create(
            drivername="postgresql+asyncpg",
            username=user,
            password=password,
            host=host,
            port=port_value,
            database=database,
            query=query or None,
        )
    )


def _database_url_from_env(env: Mapping[str, str]) -> Optional[str]:
    """Resolve the preferred database URL from environment variables."""

    candidates = [
        env.get("DATABASE_URL"),
        env.get("POSTGRES_URL"),
    ]

    for raw in candidates:
        normalized = _normalize_database_url(raw)
        if normalized:
            return normalized

    railway = _railway_env_database_url(env)
    if railway:
        return railway

    return None


DEFAULT_SQLITE_URL: str = _default_db_url()
DATABASE_URL: str = _database_url_from_env(os.environ) or DEFAULT_SQLITE_URL

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


async def init_models() -> None:
    """
    Import all model modules so they register with Base, then create tables.
    Run this once on startup for an empty DB.
    """

    # Ensure SQLAlchemy knows about every mapped class
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
