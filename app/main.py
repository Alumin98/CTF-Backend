from fastapi import FastAPI
from app.database import Base, engine

# Explicitly import all models so they're registered before table creation
from app.models import user, role, team, team_member, category, challenge, hint, challenge_tag, event

app = FastAPI()

# Auto-create all tables in the DB on startup
Base.metadata.create_all(bind=engine)
