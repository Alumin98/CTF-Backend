import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app import schema_upgrades


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _create_legacy_schema(conn):
    await conn.exec_driver_sql(
        """
        CREATE TABLE submissions (
            id INTEGER PRIMARY KEY,
            challenge_id INTEGER,
            user_id INTEGER,
            flag TEXT,
            created_at DATETIME
        )
        """
    )
    await conn.exec_driver_sql(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL
        )
        """
    )
    await conn.exec_driver_sql(
        """
        CREATE TABLE hints (
            id INTEGER PRIMARY KEY,
            challenge_id INTEGER NOT NULL
        )
        """
    )
    await conn.exec_driver_sql(
        """
        CREATE TABLE challenges (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            category_id INTEGER,
            flag TEXT,
            points INTEGER,
            difficulty INTEGER,
            docker_image TEXT,
            is_active BOOLEAN,
            is_private BOOLEAN,
            visible_from DATETIME,
            visible_to DATETIME,
            created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            competition_id INTEGER,
            unlocked_by_id INTEGER
        )
        """
    )
    await conn.exec_driver_sql(
        """
        CREATE TABLE challenge_instances (
            id INTEGER PRIMARY KEY,
            challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status VARCHAR(32) NOT NULL DEFAULT 'starting',
            container_id VARCHAR(128),
            connection_info JSON,
            error_message TEXT,
            started_at DATETIME,
            expires_at DATETIME,
            created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        )
        """
    )


@pytest.mark.anyio
async def test_upgrades_backfill_challenge_columns():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await _create_legacy_schema(conn)
        await conn.execute(
            text(
                "INSERT INTO challenges (id, title, description, category_id, flag, points, difficulty, docker_image, is_active, is_private, created_at) "
                "VALUES (1, 'Warmup', 'desc', 1, 'flag', 100, 1, 'img', 1, 0, CURRENT_TIMESTAMP)"
            )
        )
        await schema_upgrades.run_post_creation_upgrades(conn)

        columns = (await conn.exec_driver_sql("PRAGMA table_info('challenges')")).all()
        column_names = {row[1] for row in columns}
        assert {"deployment_type", "service_port", "always_on"}.issubset(column_names)

        result = await conn.execute(text("SELECT deployment_type FROM challenges WHERE id = 1"))
        assert result.scalar_one() == "dynamic_container"
    await engine.dispose()


@pytest.mark.anyio
async def test_upgrades_make_challenge_instance_user_nullable():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await _create_legacy_schema(conn)
        await conn.execute(text("INSERT INTO challenges (id, title, created_at) VALUES (1, 'One', CURRENT_TIMESTAMP)"))
        await conn.execute(text("INSERT INTO users (id, username) VALUES (5, 'player')"))
        await conn.execute(
            text(
                "INSERT INTO challenge_instances (id, challenge_id, user_id, status, created_at, updated_at) "
                "VALUES (10, 1, 5, 'running', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

        await schema_upgrades.run_post_creation_upgrades(conn)

        pragma_rows = (await conn.exec_driver_sql("PRAGMA table_info('challenge_instances')")).all()
        user_column = next(row for row in pragma_rows if row[1] == "user_id")
        assert not user_column[3], "user_id should be nullable after upgrade"

        stored = await conn.execute(text("SELECT id, user_id FROM challenge_instances"))
        assert stored.mappings().all() == [{"id": 10, "user_id": 5}]
    await engine.dispose()
