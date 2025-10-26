# CTF Backend

FastAPI-based backend for the Capture the Flag platform.

## Quickstart (Docker)
```powershell
docker compose up --build
```
- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Hot reload is enabled on the backend container; edits to the source code refresh automatically.

### Troubleshooting Docker on Windows (VS Code)
If you see an error such as `unable to get image 'ctf-backend-backend'` or Docker complains about
`dockerDesktopLinuxEngine`, the Docker engine is not running. Fix it with the steps below:

1. **Start Docker Desktop** – Launch Docker Desktop manually and wait until the taskbar icon turns green
   and says "Docker Desktop is running." VS Code’s Docker extension will also show the engine status in the
   lower-right corner.
2. **Verify WSL 2 integration** – Open Docker Desktop → *Settings* → *Resources* → *WSL Integration* and make
   sure the Linux distribution you use for VS Code (e.g. `Ubuntu`) is toggled on.
3. **Retry the compose command** – Back in VS Code’s terminal, rerun:
   ```powershell
   docker compose up --build
   ```
   The compose stack now waits for Postgres to report healthy before starting the API.
4. **Still stuck?** Use `docker info` to confirm the client can reach the daemon. If that command fails,
   reboot Docker Desktop or your machine so the named pipe `//./pipe/dockerDesktopLinuxEngine` is created.

## Services
| Service     | Purpose    | Port |
|-------------|------------|------|
| backend     | FastAPI    | 8000 |
| db          | PostgreSQL | 5432 |

To experiment with containerised challenges, add a folder such as `challenges/challenge1`
and start compose with the `challenges` profile:
```powershell
docker compose --profile challenges up --build
```
If no challenge containers are present you can ignore that profile; the core stack
(`backend`, `db`, `nginx`) will run without it.

## Environment
`.env.docker` is loaded into the backend container.
```
DATABASE_URL=postgresql+asyncpg://ctf_user:ctf_pass@db:5432/ctf_db
JWT_SECRET=supersecretfortheCTF
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=60
```

> **Note**
> When pointing the API at a hosted PostgreSQL instance, update `DATABASE_URL` with that
> connection string instead. Run `docker compose down -v` before restarting so a fresh local
> database is created if you switch back to the bundled Postgres service.

You can tweak database boot timing with optional overrides:

```
DB_INIT_MAX_ATTEMPTS=10      # how many connection retries before giving up
DB_INIT_RETRY_SECONDS=1.0    # base delay (seconds) between retries; doubles each time up to 8s
```

### Running without Docker
If you prefer to launch the API directly with `uvicorn`, make sure a PostgreSQL
instance is already accepting connections on the URL defined in `DATABASE_URL`.
For local testing you can run just the database service from compose:

```powershell
# start postgres only
docker compose up db

# in a separate terminal set DATABASE_URL accordingly and start uvicorn
$Env:DATABASE_URL = "postgresql+asyncpg://ctf_user:ctf_pass@localhost:5432/ctf_db"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Alternatively, point `DATABASE_URL` to an existing PostgreSQL deployment. The
application will keep retrying the connection during startup but will now fail
hard if the database remains unreachable, matching production expectations.

## Auth Flow Examples
```bash
# Register
curl -X POST http://localhost:8000/auth/register -H "Content-Type: application/json" -d '{"email":"test@example.com","password":"P@ssw0rd!","name":"Tester"}'

# Login (get JWT)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d '{"email":"test@example.com","password":"P@ssw0rd!"}' | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Access protected endpoint
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/teams
```

## Key Endpoints
- `POST /auth/register` → create user  
- `POST /auth/login` → JWT token  
- `GET /teams` / `POST /teams` → list/create teams (auth)  
- `GET /challenges` → list challenges (auth)  
- `POST /submissions` → submit flag (auth)  
(See full reference at `/docs`.)

## Useful Docker Commands
```powershell
# Rebuild backend after changing dependencies
docker compose build backend

# Stop & wipe DB volumes
docker compose down -v

# Shell into backend container
docker compose exec backend /bin/bash
```
