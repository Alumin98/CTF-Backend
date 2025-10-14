# app/database.py
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)


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


def _resolve_database_url() -> str:
    raw_url = os.getenv("DATABASE_URL")
    normalized = _normalize_database_url(raw_url)

    if normalized:
        return normalized

    # When pytest drives the import graph it loads its own modules first. Allow
    # the lightweight SQLite fallback in that context so unit tests run without
    # a real PostgreSQL service.
    if "pytest" in sys.modules:
        return _default_db_url()

    raise RuntimeError(
        "DATABASE_URL is not configured. Start the docker-compose stack so the "
        "PostgreSQL service is available, or export DATABASE_URL before "
        "running the API directly. See README.md for detailed instructions."
    )


DATABASE_URL: str = _resolve_database_url()

# Optional echo flag for local debugging
ECHO = os.getenv("SQLALCHEMY_ECHO", "0").lower() in {"1", "true", "yes"}

# Create async engine
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=ECHO,
    pool_pre_ping=True,
)

# IMPORTANT: expire_on_commit=False prevents lazy refresh after commit,
# which avoids MissingGreenlet when a route reads ORM attributes
# (e.g., team.team_name) after a commit within the same request.
SessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    """
    FastAPI dependency that yields an AsyncSession.
    """
    async with SessionLocal() as session:
        yield session


def ensure_submission_schema(connection) -> None:
    """Ensure legacy databases include the columns expected by the ORM."""

    inspector = inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("submissions")}

    if "submitted_hash" not in columns:
        logger.info("Adding missing submissions.submitted_hash column")
        connection.execute(
            text("ALTER TABLE submissions ADD COLUMN submitted_hash VARCHAR(255)")
        )
        connection.execute(
            text("UPDATE submissions SET submitted_hash = '' WHERE submitted_hash IS NULL")
        )
        connection.execute(
            text("ALTER TABLE submissions ALTER COLUMN submitted_hash SET NOT NULL")
        )
