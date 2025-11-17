# CTF Backend

FastAPI backend for managing a Capture the Flag (CTF) competition platform. It exposes REST APIs for authentication, team play, challenge delivery (including dynamic containers), scoring, and admin operations. The service is container-friendly and can be deployed locally with Docker or run directly with Uvicorn for development.

## Table of contents
- [Features](#features)
- [Architecture & Tech stack](#architecture--tech-stack)
- [Getting started](#getting-started)
  - [Running with Docker Compose](#running-with-docker-compose)
  - [Running locally without Docker](#running-locally-without-docker)
- [Environment configuration](#environment-configuration)
  - [Challenge runner modes](#challenge-runner-modes)
- [Useful commands](#useful-commands)
- [API documentation](#api-documentation)
- [Testing](#testing)
- [Deployment notes](#deployment-notes)

## Features
- **JWT-based authentication & user profiles** – register/login, profile edits, admin bootstrap, and password reset email flows.
- **Team lifecycle management** – create/join/leave/transfer leadership, soft-delete with participation checks, and admin listings.
- **Challenge catalog** – challenge CRUD, tags, hints, attachments, visibility windows, deployment types, and solver statistics.
- **Dynamic challenge instances** – per-user or shared containers with TTL, cleanup tasks, and runner health checks.
- **Flag submissions & scoring** – dynamic scoring with hint penalties, first blood + fast solver achievements, and scoreboard aggregation.
- **Attachments and downloads** – signed S3 links or local file streaming with visibility enforcement.

## Architecture & Tech stack
- **Framework:** [FastAPI](https://fastapi.tiangolo.com/) with automatic OpenAPI docs.
- **Persistence:** SQLAlchemy ORM + async sessions, defaults to SQLite (`test.db`) but supports PostgreSQL via `DATABASE_URL`.
- **Security:** OAuth2 password flow, Argon2 hashing for flags, JWT access tokens, rate-limited submissions.
- **Background services:** Container runner using Docker SDK (local or remote) with scheduled cleanup, email notifications for password resets, and storage abstraction for attachments.
- **Containerization:** Dockerfile + docker-compose stack with backend API and optional nginx proxy.

## Getting started
### Running with Docker Compose
```bash
docker compose up --build
```
- API base URL: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- A SQLite database (`test.db`) is created inside the mounted repo so data persists between restarts.
- Hot reload is enabled via `uvicorn --reload` in the backend container.

If Docker Desktop is required (e.g., on Windows), ensure the engine is running before invoking Compose so the backend container can build immediately.

### Running locally without Docker
Install dependencies, then start Uvicorn:
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
By default the API uses the same SQLite database file. To switch to PostgreSQL (or any SQLAlchemy-supported engine), export `DATABASE_URL`, e.g.:
```bash
export DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/ctf"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment configuration
Create a `.env` (or `.env.docker`) file and define the variables relevant to your deployment.

| Variable | Description |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy connection string. Defaults to bundled SQLite when unset. |
| `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRY_MINUTES` | Settings for signing access tokens. |
| `ALLOWED_ORIGINS` | Optional comma-separated list for enabling CORS. |
| `FLAG_SUBMISSION_RATE_LIMIT`, `FLAG_SUBMISSION_RATE_WINDOW` | Enable rate limiting for flag submissions (requests per window in seconds). |
| `CHALLENGE_INSTANCE_TIMEOUT`, `CHALLENGE_INSTANCE_CLEANUP_INTERVAL` | Control dynamic container TTL and cleanup cadence. |
| `CHALLENGE_ACCESS_BASE_URL` | Public base URL used when constructing instance/attachment links. |
| `ENABLE_ADMIN_BOOTSTRAP`, `ADMIN_BOOTSTRAP_TOKEN` | Optional bootstrap flow to promote the first admin. |
| `MAIL_*` variables (see `emailer.py`) | SMTP settings for password reset emails. |

### Challenge runner modes
Set `CHALLENGE_RUNNER` to choose how the platform provisions runtime environments:

| Runner | Description | Extra settings |
| --- | --- | --- |
| `local` (default) | Launches Docker containers through the host socket shared via Compose. | Mount `/var/run/docker.sock` in Docker environments. |
| `remote-docker` | Connects to a TCP/TLS Docker daemon. | Provide `CHALLENGE_DOCKER_HOST` plus optional `CHALLENGE_DOCKER_TLS_*` cert paths. |
| `kubernetes` | Reserved for future support; runner health returns `unavailable`. | – |

Example remote runner configuration:
```env
CHALLENGE_DOCKER_HOST=tcp://1.2.3.4:2376
CHALLENGE_DOCKER_TLS_VERIFY=1
CHALLENGE_DOCKER_TLS_CA_CERT=/app/certs/ca.pem
CHALLENGE_DOCKER_TLS_CERT=/app/certs/client-cert.pem
CHALLENGE_DOCKER_TLS_KEY=/app/certs/client-key.pem
```
Mount the certificate directory into the backend container when needed.

## Useful commands
```bash
# Rebuild backend after dependency changes
docker compose build backend

# Stop & remove containers
docker compose down

# Exec into the backend container
docker compose exec backend /bin/bash
```

## API documentation
- Browse Swagger UI at `/docs` and Redoc at `/redoc` when the service is running.
- Key endpoints include `/auth/register`, `/auth/login`, `/teams`, `/challenges`, `/submissions/submit/`, `/scoreboard`, and `/runner/health`.

## Testing
Run the Python test suite:
```bash
pytest
```

## Deployment notes
- The backend exposes a `/health` endpoint for liveness checks and `/runner/health` for container-runner diagnostics.
- Use environment variables (`DB_INIT_MAX_ATTEMPTS`, `DB_INIT_RETRY_SECONDS`, `DB_ALLOW_SQLITE_FALLBACK`) to tune startup retries when pointing at managed databases.
- Challenge attachments can be stored on the local filesystem or an S3-compatible bucket. Configure storage credentials in `app/services/storage.py` if you need remote storage.
