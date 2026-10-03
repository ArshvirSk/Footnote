# Footnote

Managed SEO + AEO/GEO platform: track how brands appear in AI answers and Google, then run the content, technical, and off-site work that improves it.

## Local Setup

### Prerequisites
- Docker & Docker Compose v2
- Node.js 20+ (for frontend dev outside Docker)
- Python 3.12+ (for backend dev outside Docker)

### Quick Start

```bash
# 1. Clone and copy env
cp .env.example .env

# 2. Bring up all services
docker compose up --build

# 3. Apply migration and seed
docker compose exec api python -m scripts.seed
```

Services will be available at:
- **Web (Next.js):** http://localhost:3000
- **API (FastAPI):** http://localhost:8000
- **API Docs:** http://localhost:8000/docs
- **Postgres:** localhost:5432
- **Redis:** localhost:6379

### Environment Variables

See `.env.example` for all required variables. Key ones:
- `DATABASE_URL` — Postgres connection string
- `REDIS_URL` — Redis connection string
- `SUPABASE_JWT_SECRET` — JWT secret for auth verification
- `SUPABASE_SERVICE_ROLE_KEY` — Service role key for workers
- `ENCRYPTION_KEY` — AES-256-GCM key for encrypting CMS/OAuth credentials

### Running Tests

```bash
# Backend tests
docker compose exec api pytest -v

# Frontend type check + lint
docker compose exec web npm run lint
docker compose exec web npm run typecheck

# RLS tests specifically
docker compose exec api pytest tests/test_rls.py -v

# All CI checks
docker compose exec api pytest -v && docker compose exec web npm run lint && docker compose exec web npm run typecheck
```

### Manual Collection Batch

```bash
# Trigger a no-op daily batch (Phase 0 skeleton)
docker compose exec worker python -c "import asyncio; from app.worker import run_daily_batch; asyncio.run(run_daily_batch({'client_id': 'demo'}))"
```

## Project Structure

```
footnote/
├─ apps/
│  ├─ web/            # Next.js: /ops and /portal route groups
│  └─ feeds-edge/     # Cloudflare Worker for /feeds proxy (Phase 5)
├─ services/
│  ├─ api/            # FastAPI
│  ├─ workers/        # collectors, parsers, crawler, sync, publishers
│  └─ agents/         # LangGraph graphs + prompts (Phase 3+)
├─ packages/
│  ├─ schemas/        # shared Pydantic/TS types
│  └─ evals/          # golden sets for judge + content checks
├─ db/migrations/
└─ infra/             # docker, CI, IaC
```

## Architecture

- **Frontend:** Next.js (App Router), TypeScript, Tailwind, shadcn/ui, Recharts
- **API:** FastAPI (Python 3.12), Pydantic v2, JWT from Supabase Auth
- **Workers:** Arq (async task queue on Redis)
- **Database:** Postgres with pgvector and RLS for multi-tenancy
- **Storage:** S3-compatible for raw answers, screenshots, Feeds sites
