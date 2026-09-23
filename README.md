# JobRec

Job recommendation platform: Next.js frontend, FastAPI backend, PostgreSQL with pgvector.

**Design:** full technical design (data model, deterministic scoring engine, trained models, LLM layer, evaluation, file-by-file plan) lives in [`docs/DESIGN.md`](docs/DESIGN.md).

## Prerequisites

- Docker Desktop
- Docker Compose v2

## Run the foundation stack

```bash
copy .env.example .env
docker compose up --build
```

- App: http://localhost:3000
- API docs: http://localhost:8000/docs
- Readiness (DB probe): http://localhost:8000/api/v1/health/ready

Postgres is published on host port **55432** because 5432/5433 were already in use on this machine. The API still talks to Postgres on the Docker network at `postgres:5432`.

## Layout

- `frontend/` — Next.js App Router
- `backend/` — FastAPI + Alembic
- `docker-compose.yml` — Postgres, API, frontend
