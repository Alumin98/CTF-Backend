# CTF Backend

FastAPI-based backend for the Capture the Flag platform.

## Quickstart (Docker)
```powershell
docker compose -f .\docker-compose.local.yml up --build
```
- API: http://localhost:8000  
- Docs: http://localhost:8000/docs  

## Services
| Service     | Purpose    | Port |
|-------------|------------|------|
| backend     | FastAPI    | 8000 |
| db          | PostgreSQL | 5432 |
| pgadmin*    | DB GUI     | 5050 |

(*pgAdmin is optional – see `docker-compose.local.yml`.)

## Environment
`.env.docker` is loaded into the backend container.
```
DATABASE_URL=postgresql+asyncpg://ctf_user:ctf_pass@db:5432/ctf_db
JWT_SECRET=supersecretfortheCTF
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=60
```

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
docker compose -f .\docker-compose.local.yml build backend

# Stop & wipe DB volumes
docker compose -f .\docker-compose.local.yml down -v

# Shell into backend container
docker exec -it ctf_backend /bin/bash
```
