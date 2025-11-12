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
   The compose stack now starts the API immediately because the default SQLite database lives inside the backend container.
4. **Still stuck?** Use `docker info` to confirm the client can reach the daemon. If that command fails,
   reboot Docker Desktop or your machine so the named pipe `//./pipe/dockerDesktopLinuxEngine` is created.

## Services
| Service | Purpose | Port |
|---------|---------|------|
| backend | FastAPI | 8000 |

To experiment with containerised challenges, add a folder such as `challenges/challenge1`
and start compose with the `challenges` profile:
```powershell
docker compose --profile challenges up --build
```
If no challenge containers are present you can ignore that profile; the core stack
(`backend`, `nginx`) will run without it.

## Environment
`.env.docker` is loaded into the backend container.
```
DATABASE_URL=sqlite+aiosqlite:///app/test.db
JWT_SECRET=supersecretfortheCTF
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=60
```

> **Note**
> The application defaults to a file-based SQLite database (`test.db`) that lives alongside the source tree.
> If you supply a `DATABASE_URL` pointing at PostgreSQL (for example a Railway instance), the backend will automatically normalise `postgresql://` URLs to `postgresql+asyncpg://` so async drivers are used without extra configuration.

### Selecting a challenge runner

The backend can provision containers through different runners. Configure it with the `CHALLENGE_RUNNER`
environment variable (defaults to `local`). Supported values:

| Runner            | Description                                                                 |
|-------------------|-----------------------------------------------------------------------------|
| `local` (default) | Uses the Docker socket mounted from the host (Docker Desktop / compose).    |
| `remote-docker`   | Connects to a remote Docker daemon over TCP/TLS. Provide `CHALLENGE_DOCKER_HOST` and optional TLS certs via `CHALLENGE_DOCKER_TLS_*`. |
| `kubernetes`      | Reserved for future work; the API will report the runner as unavailable.    |

When `remote-docker` is selected, set these additional variables (they can be placed in `.env.docker`):

```
CHALLENGE_DOCKER_HOST=tcp://1.2.3.4:2376
CHALLENGE_DOCKER_TLS_VERIFY=1
CHALLENGE_DOCKER_TLS_CA_CERT=/app/certs/ca.pem
CHALLENGE_DOCKER_TLS_CERT=/app/certs/client-cert.pem
CHALLENGE_DOCKER_TLS_KEY=/app/certs/client-key.pem
```

Mount the certificate directory into the backend container if needed. A new `/runner/health` endpoint
exposes the runner status so you can verify connectivity from the FastAPI service.

### Static vs. dynamic challenges

Each challenge now declares a `deployment_type`:

* `dynamic_container` – per-user containers with automatic TTL and cleanup.
* `static_container` – a shared container instance. Mark `always_on=true` to keep it running from startup.
* `static_attachment` – no runtime; players download the provided files.

Static containers can be provisioned by the admin UI or automatically at startup when `always_on` is enabled.
Use the `/runner/health` endpoint plus the admin challenge view to confirm shared instances are running.

You can tweak database boot timing with optional overrides:

```
DB_INIT_MAX_ATTEMPTS=10      # how many connection retries before giving up
DB_INIT_RETRY_SECONDS=1.0    # base delay (seconds) between retries; doubles each time up to 8s
```

### Running without Docker
If you prefer to launch the API directly with `uvicorn`, you can rely on the default SQLite database:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

To use PostgreSQL instead, point `DATABASE_URL` at your instance before starting `uvicorn`. The app will keep retrying during startup and fall back to SQLite if you enable `DB_ALLOW_SQLITE_FALLBACK=1`.

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
