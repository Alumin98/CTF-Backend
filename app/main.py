import asyncio
import logging
import os
from dotenv import load_dotenv  # load .env variables

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, OperationalError

from app import database
from app.database import async_session
from app.services.container_service import (
    InstanceLaunchError,
    get_container_service,
)

# ----- Load environment variables -----
load_dotenv()

# ----- Logging -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# ----- Import models so metadata is complete for create_all -----
from app.models import (  # noqa: F401 (imported for side effects)
    user, role, team, team_member, category, challenge,
    challenge_tag, event, hint, event_challenge,
    submission, activity_log, admin_action, competition, achievement,
    challenge_instance, challenge_attachment,
)

# ----- Routers -----
from app.routes.auth import router as auth_router
from app.routes.teams import router as team_router
from app.routes.challenges import router as challenge_router         # public challenges
from app.routes.challenge_instances import router as instance_router
from app.routes.attachments import router as attachments_router
from app.routes.admin_challenges import admin as admin_chal_router   # NEW: admin challenges
from app.routes.submissions import router as submission_router
from app.routes import competition as competition_routes
from app.routes.password_reset import router as password_reset_router
from app.routes.scoreboard import router as scoreboard_router
from app.routes.runner_health import router as runner_health_router

# ----- FastAPI app -----
app = FastAPI(
    title="CTF Backend",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ----- CORS (enabled only if ALLOWED_ORIGINS is set) -----
raw_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
if raw_origins:
    allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"
        ],
        expose_headers=["Content-Disposition"],
        max_age=86400,
    )

# ----- Include routers -----
app.include_router(auth_router, prefix="/auth")
app.include_router(team_router)
app.include_router(challenge_router)       # /challenges ...
app.include_router(instance_router)
app.include_router(attachments_router)
app.include_router(admin_chal_router)
app.include_router(submission_router)
app.include_router(competition_routes.router)
app.include_router(password_reset_router)
app.include_router(scoreboard_router)
app.include_router(runner_health_router)

# ----- Startup: ensure tables exist -----
async def _ensure_first_blood_column(conn):
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


async def _ensure_user_profile_columns(conn):
    statements = []
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


async def _ensure_challenge_deployment_columns(conn):
    if conn.dialect.name == "sqlite":
        statements = [
            "ALTER TABLE challenges ADD COLUMN deployment_type VARCHAR(32) DEFAULT 'static_attachment'",
            "ALTER TABLE challenges ADD COLUMN service_port INTEGER",
            "ALTER TABLE challenges ADD COLUMN always_on BOOLEAN DEFAULT 0",
        ]
    else:
        statements = [
            "ALTER TABLE challenges ADD COLUMN IF NOT EXISTS deployment_type VARCHAR(32) DEFAULT 'static_attachment'",
            "ALTER TABLE challenges ADD COLUMN IF NOT EXISTS service_port INTEGER",
            "ALTER TABLE challenges ADD COLUMN IF NOT EXISTS always_on BOOLEAN DEFAULT FALSE",
        ]

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


async def _relax_instance_user_constraint(conn):
    if conn.dialect.name == "sqlite":
        return  # SQLite cannot drop NOT NULL without a table rebuild

    ddl = text("ALTER TABLE challenge_instances ALTER COLUMN user_id DROP NOT NULL")
    try:
        await conn.execute(ddl)
    except DBAPIError as ddl_error:
        message = str(getattr(ddl_error, "orig", ddl_error)).lower()
        if "does not exist" in message or "not null constraint" not in message:
            # column may already be nullable or database might not support the syntax
            return
        raise


@app.on_event("startup")
async def on_startup():
    """Ensure database connectivity with simple retry logic."""

    max_attempts = int(os.getenv("DB_INIT_MAX_ATTEMPTS", "10"))
    base_delay = float(os.getenv("DB_INIT_RETRY_SECONDS", "1.0"))

    attempt = 0
    while True:
        attempt += 1
        try:
            async with database.engine.begin() as conn:
                await conn.run_sync(database.Base.metadata.create_all)
                await _ensure_first_blood_column(conn)
                await _ensure_user_profile_columns(conn)
                await _ensure_challenge_deployment_columns(conn)
                await _relax_instance_user_constraint(conn)
        except (OperationalError, DBAPIError, OSError) as exc:  # pragma: no cover - depends on timing
            if attempt >= max_attempts:
                allow_sqlite_fallback = os.getenv("DB_ALLOW_SQLITE_FALLBACK", "1").lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }

                using_sqlite_already = (
                    database.CURRENT_DATABASE_URL == database.DEFAULT_SQLITE_URL
                )

                if allow_sqlite_fallback and not using_sqlite_already:
                    logging.error(
                        "Database not reachable at %s after %s attempts: %s."
                        " Falling back to local SQLite for development.",
                        database.CURRENT_DATABASE_URL,
                        attempt,
                        exc,
                    )
                    await database.engine.dispose()
                    database.configure_engine(database.DEFAULT_SQLITE_URL)
                    from app import database as _db  # local import to refresh globals
                    global async_session
                    async_session = _db.async_session
                    attempt = 0
                    continue

                logging.exception("Database not reachable after %s attempts", attempt)
                raise

            wait_time = base_delay * min(2 ** (attempt - 1), 8)
            logging.warning(
                "Database not ready (attempt %s/%s): %s. Retrying in %.1f seconds...",
                attempt,
                max_attempts,
                exc,
                wait_time,
            )
            await asyncio.sleep(wait_time)
        else:
            logging.info(
                "CTF backend API started and database tables ensured (using %s).",
                database.CURRENT_DATABASE_URL,
            )
            service = get_container_service()
            await _ensure_always_on_static_containers(service)
            await service.start_cleanup_task(async_session)
            break

# ----- Health check endpoint -----
@app.get("/health", tags=["meta"])
async def health():
    return {"ok": True}

# (Recommended) Avoid logging secrets like DATABASE_URL / JWT_SECRET
# If you need to confirm they’re loaded, log booleans instead:
if os.getenv("DATABASE_URL"):
    logging.info("DATABASE_URL loaded.")
if os.getenv("JWT_SECRET"):
    logging.info("JWT_SECRET loaded.")
# ----- Shutdown: stop background tasks -----
@app.on_event("shutdown")
async def on_shutdown():
    service = get_container_service()
    await service.stop_cleanup_task()

async def _ensure_always_on_static_containers(service) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(Challenge).where(
                Challenge.deployment_type == DeploymentType.STATIC_CONTAINER.value,
                Challenge.always_on == True,
            )
        )
        for challenge in result.scalars().all():
            try:
                await service.ensure_static_instance(session, challenge=challenge)
            except InstanceLaunchError as exc:
                logging.error(
                    "Failed to ensure static container for challenge %s: %s",
                    challenge.id,
                    exc,
                )
from app.models.challenge import Challenge, DeploymentType
