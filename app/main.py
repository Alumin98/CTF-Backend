
from fastapi import FastAPI
from app.database import Base, engine
from app import models  # ensures all models are loaded (from __init__.py)

app = FastAPI()

# Auto-create all tables in the DB on startup
Base.metadata.create_all(bind=engine)
