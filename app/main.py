import asyncio
import logging
import os
from dotenv import load_dotenv  # load .env variables

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy.exc import OperationalError

from app.database import Base, engine

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
    submission, activity_log, admin_action, competition, achievement
)

# ----- Routers -----
from app.routes.auth import router as auth_router
from app.routes.teams import router as team_router
from app.routes.challenges import router as challenge_router         # public challenges
from app.routes.admin_challenges import admin as admin_chal_router   # NEW: admin challenges
from app.routes.submissions import router as submission_router
from app.routes import competition as competition_routes
from app.routes.password_reset import router as password_reset_router
from app.routes.scoreboard import router as scoreboard_router

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
app.include_router(admin_chal_router)      
app.include_router(submission_router)
app.include_router(competition_routes.router)
app.include_router(password_reset_router)
app.include_router(scoreboard_router)

# ----- Startup: ensure tables exist -----
@app.on_event("startup")
async def on_startup():
    """Ensure database connectivity with simple retry logic."""

    max_attempts = int(os.getenv("DB_INIT_MAX_ATTEMPTS", "10"))
    base_delay = float(os.getenv("DB_INIT_RETRY_SECONDS", "1.0"))

    attempt = 0
    while True:
        attempt += 1
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except OperationalError as exc:  # pragma: no cover - depends on timing
            if attempt >= max_attempts:
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
            logging.info("CTF backend API started and database tables ensured.")
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
