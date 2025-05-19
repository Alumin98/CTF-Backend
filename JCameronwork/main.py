from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from teams import router as team_router
from auth import router as auth_router
from challenges import router as challenge_router
from submissions import router as submission_router

app = FastAPI(
    title="CTF Backend API",
    description="This is the backend API for the Capture The Flag (CTF) platform.",
    version="1.0.0"
)

# Root route to avoid 404 on "/"
@app.get("/")
async def root():
    return {"message": "Welcome to the CTF Backend API"}

# Include routers with appropriate prefixes
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(team_router, prefix="/teams", tags=["Teams"])
app.include_router(challenge_router, prefix="/challenges", tags=["Challenges"])
app.include_router(submission_router, prefix="/submissions", tags=["Submissions"])

# Enable CORS (allow all origins for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict this for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
