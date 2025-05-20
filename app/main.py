from fastapi import FastAPI
from app.database import Base, engine

# Explicitly import all models to ensure table creation
from app.models import (
    user, role, team, team_member, category, challenge,
    challenge_tag, event, hint, event_challenge,
    submission, activity_log, admin_action
)

# ROUTE REGISTRATION
from app.routes.auth import router as auth_router
from app.routes.teams import router as team_router
from app.routes.challenges import router as challenge_router
from app.routes.submissions import router as submission_router

app = FastAPI()

# Include routers
app.include_router(auth_router, prefix="/auth")
app.include_router(team_router)
app.include_router(challenge_router)
app.include_router(submission_router)

# Auto-create all tables in the DB on startup
Base.metadata.create_all(bind=engine)
