# CTF Backend

FastAPI-based backend for the Capture the Flag platform.

## Quickstart (Docker)
```powershell
docker compose up --build
```
- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Hot reload is enabled on the backend container; edits to the source code refresh automatically.
- The `db` service is a local PostgreSQL instance that the backend waits for before it starts.

### When the stack is already running
With Docker Desktop open and `docker compose up --build` still running (the log
line `backend-1  | Application startup complete.` confirms the API is ready):

1. Visit [http://localhost:8000/docs](http://localhost:8000/docs) to exercise
   the API in your browser.
2. If you detached from the compose command, use `docker compose ps` to verify
   the `backend` and `db` containers show a state of `Up`.
3. Stream API logs at any time with `docker compose logs -f backend`.
4. Stop the stack when you are finished via `docker compose down` (add `-v` to
   wipe the database volume).

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
> When the compose stack is running this URL points at the bundled Postgres container. If you prefer
> to target a managed instance (for example the Railway database shared above), update the value to
> your connection string *before* running `docker compose up` or `uvicorn` so the backend connects to
> the correct host.

You can tweak database boot timing with optional overrides:

```
DB_INIT_MAX_ATTEMPTS=10      # how many connection retries before giving up
DB_INIT_RETRY_SECONDS=1.0    # base delay (seconds) between retries; doubles each time up to 8s
```

### Running without Docker
If you prefer to launch the API directly with `uvicorn`, make sure a PostgreSQL
instance is already accepting connections on the URL defined in `DATABASE_URL`.
The application now raises a clear error if `DATABASE_URL` is missing so you know
to start Postgres first.

#### "Connect call failed ('127.0.0.1', 5432)"
That message means the backend reached out to the host referenced in
`DATABASE_URL` (by default `localhost:5432`) but nothing is listening there yet.
Start the database service with Docker Compose or point `DATABASE_URL` to your
managed instance before launching `uvicorn`.

For local testing you can run just the database service from compose:

```powershell
# start postgres only
docker compose up db

# in a separate terminal set DATABASE_URL accordingly and start uvicorn
$Env:DATABASE_URL = "postgresql+asyncpg://ctf_user:ctf_pass@localhost:5432/ctf_db"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Alternatively, point `DATABASE_URL` to an existing PostgreSQL deployment such as
the Railway instance:

```powershell
$Env:DATABASE_URL = "postgresql://postgres:crDJrMIjfkHEZDuElDBFMIduQtsHAksF@nozomi.proxy.rlwy.net:38969/railway"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The application keeps retrying the connection during startup but will fail hard
if the database remains unreachable, matching production expectations.

### "DATABASE_URL is not configured" on startup

This error means the backend could not find a `DATABASE_URL` environment
variable. Export it (PowerShell example below) or start the Docker Compose
stack so the `.env.docker` file is loaded automatically:

```powershell
$Env:DATABASE_URL = "postgresql+asyncpg://ctf_user:ctf_pass@localhost:5432/ctf_db"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

When using Docker, run `docker compose up --build` and the backend will wait for
the `db` service before it starts serving requests.

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

## Screenshot checklist
Capture these after the stack is healthy so stakeholders can verify the end-to-end
flow without needing to run the project themselves:

1. **Docker services running** – output of `docker compose ps` showing the
   `backend` and `db` containers with a status of `Up`.
2. **Interactive API docs** – browser screenshot of
   [http://localhost:8000/docs](http://localhost:8000/docs) once FastAPI has
   generated the OpenAPI schema.
3. **Successful authentication** – the `/auth/login` request in the Swagger UI
   returning `200 OK` with a JWT token, or an equivalent `curl` response in the
   terminal.
4. **Protected endpoint access** – `GET /teams` (or another authenticated
   endpoint) succeeding with the `Authorization: Bearer <token>` header applied.
5. **Database visibility (optional)** – a psql or GUI view showing the `ctf_db`
   schema to demonstrate that PostgreSQL is the active backing store.

Saving these screenshots in a shared folder keeps QA and deployment reviewers on
the same page about what “working” looks like for this service.
