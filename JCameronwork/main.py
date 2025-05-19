from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from teams import router as team_router
from auth import router as auth_router
from challenges import router as challenge_router
from submissions import router as submission_router

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "CTF Backend is running"}

# Include routers
app.include_router(auth_router, prefix="/auth")
app.include_router(team_router)
app.include_router(challenge_router)
app.include_router(submission_router)

# CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for testing; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
