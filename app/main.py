
from fastapi import FastAPI
from app.database import Base, engine

# Import all models so they register with SQLAlchemy
from app.models import user, role, team, team_member, category, challenge


app = FastAPI()

# Automatically create tables
Base.metadata.create_all(bind=engine)
