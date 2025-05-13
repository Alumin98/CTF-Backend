
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello, Railway!"}
from app.database import Base, engine
from app.models import user

# Create tables on startup
Base.metadata.create_all(bind=engine)
