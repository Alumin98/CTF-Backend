<<<<<<< HEAD
import logging
import os  ### NEW
from dotenv import load_dotenv  ### NEW

# Load .env file
load_dotenv()  ### NEW
=======
# main.py
>>>>>>> 0195287bd5ee6bd7d6f0b58f5f8cea54f51aa919

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine

# ----- Logging -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# ----- Import models so metadata is complete for create_all -----
from app.models import (  # noqa: F401  (imported for side effects)
    user, role, team, team_member, category, challenge,
    challenge_tag, event, hint, event_challenge,
    submission, activity_log, admin_action, competition
)

# ----- Routers -----
from app.routes.auth import router as auth_router
from app.routes.teams import router as team_router
from app.routes.challenges import router as challenge_router
from app.routes.submissions import router as submission_router
from app.routes import competition as competition_routes

# ----- FastAPI app (single instance) -----
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
        allow_origins=allowed_origins,  # exact origins only
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"
        ],
        expose_headers=["Content-Disposition"],
        max_age=86400,
    )

# ----- Include routers on the SAME app -----
app.include_router(auth_router, prefix="/auth")
app.include_router(team_router)            # keep as your routes define
app.include_router(challenge_router)       # keep as your routes define
app.include_router(submission_router)      # keep as your routes define
app.include_router(competition_routes.router)

# ----- Startup: ensure tables exist -----
@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logging.info("CTF backend API started up and database tables ensured.")

<<<<<<< HEAD
from app.routes import competition
app.include_router(competition.router)

# Example usage of env vars:
db_url = os.getenv("DATABASE_URL")
jwt_secret = os.getenv("JWT_SECRET")
logging.info(f"Loaded DATABASE_URL: {db_url}")
=======
# Optional: health probe
@app.get("/health", tags=["meta"])
async def health():
    return {"ok": True}
>>>>>>> 0195287bd5ee6bd7d6f0b58f5f8cea54f51aa919
