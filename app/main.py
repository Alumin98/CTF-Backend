import asyncio
import logging
import os
from dotenv import load_dotenv  # load .env variables

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy.exc import DBAPIError, OperationalError

import app.database as database
from app.services.container_service import get_container_service

# ----- Load environment variables -----
load_dotenv()

# ----- Logging -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# ----- Routers -----
from app.routes.auth import router as auth_router
from app.routes.teams import router as team_router
from app.routes.challenges import router as challenge_router         # public challenges
from app.routes.challenge_instances import router as instance_router
from app.routes.attachments import router as attachments_router
from app.routes.admin_challenges import admin as admin_chal_router   # NEW: admin challenges
from app.routes import admin_categories
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
app.include_router(admin_categories.router)
app.include_router(submission_router)
app.include_router(competition_routes.router)
app.include_router(password_reset_router)
app.include_router(scoreboard_router)
app.include_router(runner_health_router)

@app.on_event("startup")
async def on_startup():
    """Ensure database connectivity with simple retry logic."""

    print("Using DB:", database.CURRENT_DATABASE_URL)

    max_attempts = int(os.getenv("DB_INIT_MAX_ATTEMPTS", "10"))
    base_delay = float(os.getenv("DB_INIT_RETRY_SECONDS", "1.0"))

    attempt = 0

    def sqlite_fallback_allowed() -> bool:
        """Decide if we may fall back to the bundled SQLite database."""

        configured = os.getenv("DB_ALLOW_SQLITE_FALLBACK")
        if configured is not None:
            return configured.lower() in {"1", "true", "yes", "on"}

        # By default we only allow fallback when the app is already configured
        # to use the bundled SQLite database (e.g. local development without a
        # DATABASE_URL). In all other situations it's safer to fail fast so
        # that deployment misconfigurations don't go unnoticed.
        return database.CURRENT_DATABASE_URL == database.DEFAULT_SQLITE_URL
    while True:
        attempt += 1
        try:
            await database.init_models()
        except (OperationalError, DBAPIError, OSError) as exc:  # pragma: no cover - depends on timing
            if attempt >= max_attempts:
                if sqlite_fallback_allowed() and (
                    database.CURRENT_DATABASE_URL != database.DEFAULT_SQLITE_URL
                ):
                    logging.error(
                        "Database not reachable at %s after %s attempts: %s."
                        " Falling back to local SQLite for development.",
                        database.CURRENT_DATABASE_URL,
                        attempt,
                        exc,
                    )
                    await database.engine.dispose()
                    database.configure_engine(database.DEFAULT_SQLITE_URL)
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
            await get_container_service().start_cleanup_task(database.async_session)
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

