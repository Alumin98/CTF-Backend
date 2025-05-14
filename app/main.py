from fastapi import FastAPI
from app.database import Base, engine
from app.models import role, user, team

app = FastAPI()

# Create all tables when the app starts
Base.metadata.create_all(bind=engine)
