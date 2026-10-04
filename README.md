# Footnote

Managed SEO + AEO/GEO platform: track how brands appear in AI answers and Google, then run the content, technical, and off-site work that improves it.

## Status

- **Milestone 0 (reality check) — done:** [docs/REALITY_CHECK.md](docs/REALITY_CHECK.md) maps every screen, endpoint, table and worker to real / mock / stubbed, and is updated after each milestone.
- **Milestone 1 (website setup) — done:** websites list + detail, derived status + setup checklist, brand profile / aliases, brand memory, competitors, personas, dashboard action queue.
- **Milestone 2 (collection + research) — done:** prompt research agent, live engine adapters, nightly scheduler with idempotency + caps + retries, rules/LLM judge with golden set, collection health, Prompts / Prompt detail / Tracking / Gaps screens.

**What is not connected yet:** Google Search Console and GA4 (tables untouched, UI shows "Not connected. Planned."), publishing (WordPress/feeds), content generation, portal/admin sections — later milestones. Live collection needs provider API keys; without them runs fail with an explicit `set OPENAI_API_KEY …` error so nothing is ever silently faked. Mock engines exist but are an explicit opt-in (`ALLOW_MOCK_ENGINES=true`), and mock answers are marked (`raw_json.mock=true`, `-mock` model label).

## Local Setup (no Docker)

### Prerequisites
- Python 3.11+ (3.12 preferred)
- Node.js 20+
- A [Neon](https://console.neon.tech) Postgres project (pgvector and pg_trgm are available on Neon)
- Redis — only required for the Arq worker (queues, rate limits, cron). The collection pipeline can also run without Redis via the CLI runner.

### Quick Start

```bash
# 1. Configure the database (Neon CLI)
#    neon link --project-id <id> --branch production -y
#    # writes DATABASE_URL + DATABASE_URL_UNPOOLED + NEON_BRANCH into .env
#    # (manual alternative: cp .env.example .env and fill DATABASE_URL yourself)

# 2. Python environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r services/api/requirements.txt -r services/workers/requirements.txt

# 3. Apply schema to Neon (idempotent, tracks applied files in schema_migrations)
PYTHONPATH=. python -m services.api.scripts.migrate

# 4. Optional: seed demo data
PYTHONPATH=. python -m services.api.scripts.seed

# 5. Run services (separate terminals, from repo root, PYTHONPATH=.)
PYTHONPATH=. uvicorn services.api.app.main:app --port 8000    # API (avoid --reload: the Windows reloader can hang)
PYTHONPATH=. arq services.workers.app.worker.WorkerSettings   # Worker (needs Redis)
cd apps/web && npm install && npm run dev                     # Web
```

Services:
- **Web (Next.js):** http://localhost:3000
- **API (FastAPI):** http://localhost:8000
- **API Docs:** http://localhost:8000/docs

> On Windows PowerShell use `$env:PYTHONPATH="."` instead of the `PYTHONPATH=.` prefix.

**No Redis?** Run worker jobs directly:

```bash
PYTHONPATH=. python -m services.workers.app.runner daily-batch            # schedule + collect today (all websites)
PYTHONPATH=. python -m services.workers.app.runner run-now --client <id>  # one website now (--prompt <id> for one prompt)
PYTHONPATH=. python -m services.workers.app.runner rollup                 # daily metrics + gap detection for today
# add --mock to opt in to mock engines for that run (no provider keys needed)
```

**Dev login** (ENVIRONMENT != production): `POST /api/v1/auth/dev-login` with `{"email": "operator@footnote.dev"}` returns a JWT; the web app stores it in localStorage.

### Environment Variables

See [.env.example](.env.example) for all required variables. Key ones:
- `DATABASE_URL` / `DATABASE_URL_UNPOOLED` — Neon pooled + direct endpoints (pulled by `neon link` / `neon deploy`); `DATABASE_URL_SYNC` is derived automatically (prefers the unpooled endpoint for migrations/tests)
- `REDIS_URL` — Redis connection string (Arq worker only)
- `SUPABASE_JWT_SECRET` — JWT secret for auth verification
- `ENCRYPTION_KEY` — AES-256-GCM key for encrypting CMS/OAuth credentials
- `EDGE_SERVICE_TOKEN` — shared token for the Feeds edge worker → API calls
- `STRIPE_WEBHOOK_SECRET` — empty disables `/webhooks/stripe`
- `OPENAI_API_KEY`, `GEMINI_API_KEY`, `PERPLEXITY_API_KEY`, `XAI_API_KEY`, `ANTHROPIC_API_KEY` — one live engine per key; missing keys fail runs explicitly unless `ALLOW_MOCK_ENGINES=true`
- `ALLOW_MOCK_ENGINES` — explicit opt-in to mock collection for local demos (default `false`)
- `COLLECTION_JITTER_SECONDS` (default 120) and `DEFAULT_DAILY_CALL_CAP` (default 2000) — scheduler knobs
- `JUDGE_MODE` (`rules` default, or `llm`) and `JUDGE_MODEL` (default `gpt-5-mini`) — mention judge

### Running Checks

```bash
# Backend
PYTHONPATH=. python -m ruff check .                # lint
PYTHONPATH=. python -m mypy services packages      # typecheck (strict, via pyproject)
PYTHONPATH=. pytest services -q                    # tests (need DATABASE_URL_SYNC reachable)
PYTHONPATH=. python packages/evals/judge_eval.py   # golden-set gate (>= 30 cases, >= 95% agreement)

# Frontend
cd apps/web
npm run lint
npx tsc --noEmit
npm run build
```

CI runs the same checks on push/PR (see [.github/workflows/ci.yml](.github/workflows/ci.yml)); the backend job provisions an ephemeral Postgres service container in GitHub Actions (this is CI infra, independent of local development).

## Project Structure

```
footnote/
├─ apps/
│  ├─ web/            # Next.js: /ops and /portal route groups
│  └─ feeds-edge/     # Cloudflare Worker for /feeds proxy (Phase 5)
├─ services/
│  ├─ api/            # FastAPI (routes, auth, brand memory, research agent, website status)
│  ├─ workers/        # engine adapters, parser/judge, scheduler, rollup, crawler, publishers, CLI runner
│  └─ agents/         # LangGraph graphs + prompts (Phase 3+)
├─ packages/
│  ├─ schemas/        # shared Pydantic/TS types
│  └─ evals/          # golden sets (judge) + content check fixtures
├─ db/
│  ├─ migrations/     # 0000_auth, 0001_init, 0002_clients_is_demo, 0003_m2_collection (applied by services/api/scripts/migrate.py)
│  └─ seed.sql
└─ docs/              # product docs, reality check, audit reports
```

## Architecture

- **Frontend:** Next.js (App Router), TypeScript, Tailwind, shadcn/ui, Recharts
- **API:** FastAPI (Python 3.12), Pydantic v2, JWT from Supabase Auth
- **Workers:** Arq (async task queue on Redis) + a Redis-less CLI runner for manual/cron batches
- **Database:** Neon Postgres with pgvector and RLS for multi-tenancy
- **Storage:** S3-compatible for raw answers, screenshots, Feeds sites

### Collection pipeline (Milestone 2)

- **Engines:** OpenAI (`gpt-5-search-api` + web search), Gemini (`google_search` grounding), Perplexity (Agent API, `fast` preset), xAI Responses (`grok-4.7` + web search), Anthropic Messages (`claude-sonnet-5-5` + web search tool). Citations are parsed from each provider's own contract; raw JSON is always kept as the source of truth.
- **Scheduling:** k=3 runs per prompt × engine per UTC day, jittered fan-out, per-website daily call cap, retries with backoff (429/5xx). Idempotency key `(client, prompt, engine, run_index, day)`; re-running a day is a no-op and manual runs add a new run index instead of overwriting raw answers.
- **Judging:** deterministic `rules-v2` judge (alias + fuzzy brand/competitor detection, citations, domain taxonomy) by default; optional LLM judge with automatic fallback. The golden set (40 hand-labelled fixtures) gates changes at ≥ 95% agreement per axis.
- **Outputs:** daily metrics, domain citation ranking, competitor matrix, gaps/slips with raw-answer evidence behind every detection.
