import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

from fastapi import FastAPI
from app.database import Base, engine

# Explicitly import all models to ensure table creation
from app.models import (
    user, role, team, team_member, category, challenge,
    challenge_tag, event, hint, event_challenge,
    submission, activity_log, admin_action, competition
)

# ROUTE REGISTRATION
from app.routes.auth import router as auth_router
from app.routes.teams import router as team_router
from app.routes.challenges import router as challenge_router
from app.routes.submissions import router as submission_router

app = FastAPI()

app.include_router(auth_router, prefix="/auth")
app.include_router(team_router)
app.include_router(challenge_router)
app.include_router(submission_router)

@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logging.info("CTF backend API started up and database tables ensured.")

from app.routes import competition
app.include_router(competition.router)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI(title="CTF Backend")

# Only enable CORS if ALLOWED_ORIGINS is set (zero-risk)
raw_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
if raw_origins:
    allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,     # exact origins only
        allow_credentials=True,            # OK with exact origins
        allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
        allow_headers=["Authorization","Content-Type","Accept","Origin","X-Requested-With"],
        expose_headers=["Content-Disposition"],
        max_age=86400,
    )
