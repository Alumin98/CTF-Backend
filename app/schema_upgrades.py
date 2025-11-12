"""Idempotent schema upgrades applied after metadata.create_all()."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection


async def ensure_first_blood_column(conn: AsyncConnection) -> None:
    if conn.dialect.name == "sqlite":
        ddl = text(
            "ALTER TABLE submissions ADD COLUMN first_blood "
            "BOOLEAN NOT NULL DEFAULT 0"
        )
    else:
        ddl = text(
            "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS first_blood "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )

    try:
        await conn.execute(ddl)
    except DBAPIError as ddl_error:  # column may already exist
        message = str(getattr(ddl_error, "orig", ddl_error)).lower()
        if not any(
            phrase in message
            for phrase in (
                "duplicate column name",
                "already exists",
                'column "first_blood" of relation "submissions" already exists',
            )
        ):
            raise


async def ensure_user_profile_columns(conn: AsyncConnection) -> None:
    statements: list[str] = []
    if conn.dialect.name == "sqlite":
        statements.append("ALTER TABLE users ADD COLUMN display_name TEXT")
        statements.append("ALTER TABLE users ADD COLUMN bio TEXT")
    else:
        statements.append(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(120)"
        )
        statements.append("ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT")

    for ddl in statements:
        try:
            await conn.execute(text(ddl))
        except DBAPIError as ddl_error:
            message = str(getattr(ddl_error, "orig", ddl_error)).lower()
            if not any(
                phrase in message
                for phrase in (
                    "duplicate column name",
                    "already exists",
                    'column "display_name" of relation "users" already exists',
                    'column "bio" of relation "users" already exists',
                )
            ):
                raise


async def ensure_hint_order_index_column(conn: AsyncConnection) -> None:
    if conn.dialect.name == "sqlite":
        ddl = "ALTER TABLE hints ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0"
    else:
        ddl = (
            "ALTER TABLE hints ADD COLUMN IF NOT EXISTS order_index "
            "INTEGER NOT NULL DEFAULT 0"
        )

    try:
        await conn.execute(text(ddl))
    except DBAPIError as ddl_error:
        message = str(getattr(ddl_error, "orig", ddl_error)).lower()
        if not any(
            phrase in message
            for phrase in (
                "duplicate column name",
                "already exists",
                'column "order_index" of relation "hints" already exists',
            )
        ):
            raise


async def ensure_challenge_deployment_columns(conn: AsyncConnection) -> None:
    statements: list[str] = []
    if conn.dialect.name == "sqlite":
        statements.append(
            "ALTER TABLE challenges ADD COLUMN deployment_type TEXT DEFAULT 'dynamic_container'"
        )
        statements.append("ALTER TABLE challenges ADD COLUMN service_port INTEGER")
        statements.append("ALTER TABLE challenges ADD COLUMN always_on BOOLEAN NOT NULL DEFAULT 0")
    else:
        statements.append(
            "ALTER TABLE challenges ADD COLUMN IF NOT EXISTS deployment_type "
            "VARCHAR(32) NOT NULL DEFAULT 'dynamic_container'"
        )
        statements.append(
            "ALTER TABLE challenges ADD COLUMN IF NOT EXISTS service_port INTEGER"
        )
        statements.append(
            "ALTER TABLE challenges ADD COLUMN IF NOT EXISTS always_on "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )

    for ddl in statements:
        try:
            await conn.execute(text(ddl))
        except DBAPIError as ddl_error:
            message = str(getattr(ddl_error, "orig", ddl_error)).lower()
            if not any(
                phrase in message
                for phrase in (
                    "duplicate column name",
                    "already exists",
                    'column "deployment_type" of relation "challenges" already exists',
                    'column "service_port" of relation "challenges" already exists',
                    'column "always_on" of relation "challenges" already exists',
                )
            ):
                raise

    await conn.execute(
        text(
            "UPDATE challenges SET deployment_type = 'dynamic_container' "
            "WHERE deployment_type IS NULL"
        )
    )


async def ensure_instance_user_nullable(conn: AsyncConnection) -> None:
    if conn.dialect.name == "sqlite":
        result = await conn.exec_driver_sql("PRAGMA table_info('challenge_instances')")
        columns = result.mappings().all()
        if not columns:
            return

        user_column = next((col for col in columns if col["name"] == "user_id"), None)
        if not user_column or not user_column["notnull"]:
            return

        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            await conn.exec_driver_sql("DROP TABLE IF EXISTS challenge_instances__tmp")
            await conn.exec_driver_sql(
                """
                CREATE TABLE challenge_instances__tmp (
                    id INTEGER PRIMARY KEY,
                    challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
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
            await conn.exec_driver_sql(
                """
                INSERT INTO challenge_instances__tmp (
                    id,
                    challenge_id,
                    user_id,
                    status,
                    container_id,
                    connection_info,
                    error_message,
                    started_at,
                    expires_at,
                    created_at,
                    updated_at
                )
                SELECT
                    id,
                    challenge_id,
                    user_id,
                    status,
                    container_id,
                    connection_info,
                    error_message,
                    started_at,
                    expires_at,
                    created_at,
                    updated_at
                FROM challenge_instances
                """
            )
            await conn.exec_driver_sql("DROP TABLE challenge_instances")
            await conn.exec_driver_sql("ALTER TABLE challenge_instances__tmp RENAME TO challenge_instances")
        finally:
            await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        return

    ddl = text("ALTER TABLE challenge_instances ALTER COLUMN user_id DROP NOT NULL")
    try:
        await conn.execute(ddl)
    except DBAPIError as ddl_error:
        message = str(getattr(ddl_error, "orig", ddl_error)).lower()
        if "does not exist" in message or "already" in message:
            return
        if "not null" in message:
            return
        raise


def upgrade_order() -> tuple:
    return (
        ensure_first_blood_column,
        ensure_user_profile_columns,
        ensure_hint_order_index_column,
        ensure_challenge_deployment_columns,
        ensure_instance_user_nullable,
    )


async def run_post_creation_upgrades(conn: AsyncConnection) -> None:
    for step in upgrade_order():
        await step(conn)
