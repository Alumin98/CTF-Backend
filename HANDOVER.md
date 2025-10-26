# HANDOVER.md – CTF Backend

## One-time setup
1. Install Docker Desktop and ensure it is running.
2. From the project root:
   ```powershell
   docker compose up --build
   ```

3. Open in browser:
   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs

## Services & Ports
| Service  | Port | Notes               |
|----------|------|---------------------|
| backend  | 8000 | FastAPI backend     |
| db       | 5432 | PostgreSQL database |

## Credentials
- **Postgres**: `ctf_user / ctf_pass` → DB: `ctf_db`

## Environment
Values loaded from `.env.docker`.
```
DATABASE_URL=postgresql+asyncpg://ctf_user:ctf_pass@db:5432/ctf_db
JWT_SECRET=supersecretfortheCTF
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=60
```

If you need to connect to a hosted PostgreSQL instance, update `DATABASE_URL` accordingly and
restart the stack with `docker compose down -v` followed by `docker compose up --build` so the
local volume resets.

## Start / Stop
```powershell
# Start services (build if needed)
docker compose up --build

# Stop services
docker compose down
```

## Verification checklist
1. Visit `http://localhost:8000/docs` → interactive docs load.
2. `docker ps` shows `ctf-backend-backend` and `ctf-backend-db` running.
3. Register + login (see README Auth flow) returns valid JWT token.
4. Protected endpoints (e.g. /teams) respond with `Authorization: Bearer <token>` header.
