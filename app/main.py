from fastapi import FastAPI
from app.database import Base, engine

# Explicitly import all models to ensure table creation
from app.models import (
    user, role, team, team_member, category, challenge,
    challenge_tag, event, hint, event_challenge,
    submission, activity_log
)

app = FastAPI()

# Auto-create all tables in the DB on startup
Base.metadata.create_all(bind=engine)
