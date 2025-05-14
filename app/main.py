from fastapi import FastAPI
from app.database import Base, engine

# Import all models to register with SQLAlchemy metadata
from app.models import user, role, team

app = FastAPI()

# Create tables
Base.metadata.create_all(bind=engine)
