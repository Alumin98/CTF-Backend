# app/main.py

import logging
from fastapi import FastAPI

from app.database import Base, engine  # ✅ needed to create tables

# ✅ Import ALL models so SQLAlchemy knows what to create
from app.models import (
    user, role, team, team_member, category, challenge,
    challenge_tag, event, hint, event_challenge,
    submission, activity_log, admin_action, competition
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

tags_metadata = [
    {"name": "auth", "description": "Register, login, tokens"},
    {"name": "teams", "description": "Create, join, list teams"},
    {"name": "challenges", "description": "Browse challenges and hints"},
    {"name": "submissions", "description": "Submit flags and get results"},
    {"name": "admin", "description": "Admin-only actions and settings"},
]

app = FastAPI(
    title="CTF Backend API",
    description=(
        "Backend for CTF competitions: teams, challenges, submissions, and leaderboard.\n\n"
        "Use the **Authorize** button to paste your JWT (Bearer token) before calling protected routes."
    ),
    version="2.0.0",
    openapi_tags=tags_metadata,
)

@app.get("/health")
async def health():
    return {"ok": True}

# ---- Routers ----
from app.routes.auth import router as auth_router
app.include_router(auth_router, prefix="/auth", tags=["auth"])

from app.routes.teams import router as team_router
app.include_router(team_router, tags=["teams"])

# ---- Create tables on startup (SQLite/Postgres) ----
@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logging.info("✅ Tables ensured (created if missing).")
