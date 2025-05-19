from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Importing routers from feature modules
from teams import router as team_router
from auth import router as auth_router
from challenges import router as challenge_router
from submissions import router as submission_router

app = FastAPI()

# Root route for health check or simple API message
@app.get("/")
def root():
    return {"message": "Welcome to the CTF Platform API. The backend is running."}

# Registering routers with specific prefixes
app.include_router(auth_router, prefix="/auth")
app.include_router(team_router)
app.include_router(challenge_router)
app.include_router(submission_router)

# CORS middleware for frontend-backend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development; change to specific domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
