# Footnote — Reality Check (Step 0)

Date: 2026-10-04 · Branch: `main` · Environment: local API (`:8000`) + Next dev (`:3000`) against Neon project `twilight-brook-95311249`, branch `production` (PG 18.6).

This document walks every `/ops` and `/portal` route, every API endpoint and every worker job, and records whether it is **real** (executes production logic against the database), **partial** (some real behavior, some gaps), or **mock** (hardcoded / fixture data / stubbed external call). It is the baseline for the milestone plan; it will be updated as milestones land.

Legend:

- **real** — the code path runs against the DB / live network and its outputs are computed, not invented.
- **partial** — reads or writes real data but is missing a required behaviour (generation, validation, history, gating…).
- **mock** — hardcoded numbers/fixtures in code or a stubbed external call that pretends to succeed.
- **unused** — schema exists, no code reads or writes it.

---

## 0. Blockers and assumptions (read first)

| # | Finding | Safest option taken |
| --- | --- | --- |
| B1 | **No engine provider keys in `.env`** (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `PERPLEXITY_API_KEY`, `XAI_API_KEY`, `ANTHROPIC_API_KEY` all absent). `get_adapter()` silently falls back to `MockEngineAdapter`, so a "collection run" today writes simulated answers that look real in the DB. | Adapters are being hardened: mock mode becomes **explicit opt-in** (`ALLOW_MOCK_ENGINES=true`) and mock rows are marked (`raw_json.mock=true`, `model_label` suffix `-mock`) so no view can present them as real. Live collection requires the user to add at least one provider key (manual setup — listed in the milestone report). |
| B2 | **No `OPENAI_API_KEY`** also blocks real embeddings for brand memory (`embed_publication` writes the constant vector `[0.02]*1536`). | Brand memory ingestion will use a real embeddings provider when configured; without a key the ingest endpoint returns a clear configuration error rather than writing fake vectors. |
| B3 | **No Redis** on this machine. Arq crons (nightly batch, rollup, GSC/GA4 sync, digest) therefore never fire; only the in-process runner (`services/workers/app/runner.py`) can execute jobs. | Keep the Redis-less runner as the supported local path; document a Windows scheduled task as the nightly driver. A real Redis remains the production path. |
| B4 | **Google Search Console / GA4 are deferred** by scope decision. `integrations` OAuth callback is a stub and `sync_gsc_data` / `sync_ga4_data` insert hardcoded rows. | Do not run those jobs; UI shows "Not connected. Planned." — no fake Google numbers anywhere. The stub sync code will be disabled so it can never write invented data. |
| B5 | **Current DB contains test/demo rows** mixed with the user's real site: `Acme Corp` (seeded demo, 20 prompts / 300 fixture answers / 7 personas), `Test Site` (`example.com`, audit-only), `Client A` / `Client B` (`client-a.com` / `client-b.com` — leftover test fixtures from `conftest.py`). Only **DBA** (`www.dbaconsultants.co.in`) is real, and it currently has **0 prompts, 0 answers, 0 brand profile, 0 competitors, 0 personas**, 2 audits (best score 91/100). | Migration `0002` adds `clients.is_demo`; Acme/Test Site/Client A/Client B are flagged demo and hidden by default behind a toggle with a "Demo data" badge. DBA is the first real client for the end-to-end path. |

Assumptions:

- "Real data" means: values computed by our code from the DB or from live network calls we control. Fixture rows are acceptable only for demo-flagged websites.
- A human operator (the user) supplies the WordPress sandbox credentials, and provider API keys, when the relevant milestone needs them.

---

## 1. `/ops` routes (operator console)

| Route | State | API calls made | Notes / what's missing |
| --- | --- | --- | --- |
| `/ops` Dashboard | **mock** | none | Hardcoded KPI cards (12 approvals, 4 clients, 99.8% health). Copy says "select a client from the sidebar" but the switcher is in the header. No per-website data, no action queue. → **Milestone 1 rebuild**. |
| `/ops/analytics` | **mock** | none | Hardcoded 24 published / 18 gaps closed / 142 mentions / "+4,200 Estimated Traffic ROI"; placeholder "Recharts AreaChart component will render here"; fabricated gap rows ("Best AI CRM"). → **Milestone 6**. |
| `/ops/clients` (Websites) | **partial** | `GET /clients`, `POST /clients`, `POST /clients/{id}/audits` | Real list/create/audit-now. But: status column shows `clients.status` (all "onboarding" except Acme), no setup checklist/progress, no last-collection, no visibility, no open issues, no approvals; demo rows not distinguished; no detail page. → **Milestone 1: `/ops/websites` + `/ops/websites/[id]`**. |
| `/ops/prompts` | **partial** | `GET/POST /clients/{id}/prompts` | Real CRUD (create + list), but no edit/retire, no research agent, no sparkline, no per-engine status, cap defaults to 25 via `settings.billing_limits` (PRD allows 125), no history. → **Milestone 2** (list here is reusable). |
| `/ops/gaps` | **partial** | `GET /clients/{id}/gaps` | Real rollup output with prompt text; action button is dead ("Create Brief →" does nothing), no evidence answers, no status transitions. → **Milestones 2/4**. |
| `/ops/pipeline` | **mock** | none | Hardcoded kanban ("Best AI CRM", "Sales Funnel 101"). → **Milestone 4**. |
| `/ops/site-audit` | **real** | `GET /clients`, `GET/POST /clients/{id}/audits`, `GET /clients/{id}/audits/{id}` | Live crawl and persist; verified against DBA (91/100) and MDN. Missing per Milestone 3: PageSpeed, robots rules per AI bot, rule re-run to verify fixes, dev-brief export, findings history/status UI, team vs client_dev surfacing. |
| `/ops/admin` | **mock** | none | Fake masked OpenAI key, "Worker Status: Active" for an undeployed Cloudflare worker. → **Milestone 7** (real users/roles, audit log, spend, caps, re-parse, run logs). |
| `/login` | **real** | `POST /auth/dev-login` | Dev login only (404 in production); Supabase auth later. |
| `/` | **partial** | none | Stub redirect `/` → `/portal` claims "Phase 0" — contradicts `login` which sends operators to `/ops`. → fixed in **Milestone 1** (role-aware landing). |

## 2. `/portal` routes (client-facing)

| Route | State | Notes |
| --- | --- | --- |
| `/portal` | **mock** | Hardcoded "Acme Corp" dashboard (42% visibility, 18% citation share, 14 shipped, 3 approvals) + a fabricated engine quote. |
| `/portal/approvals` | **mock** | Two invented approvals via `setTimeout`; Review/Approve buttons do nothing, no API calls. |
| `/portal/settings` | **mock** | Fake edge endpoint + fake API key `fn_edge_98f8…`; "Rotate API Key" is a no-op. |
| `/portal` layout | **mock** | Hardcoded "Acme Corp" brand and `client@example.com`; no role gate, no client selection. |

No portal route checks the token's role or client access. → **Milestone 7** (read-only + approvals, gated by `client_approver`/`client_viewer`, "View as client" preview).

---

## 3. API endpoints

Routers mounted in `services/api/app/main.py` under `/api/v1` (except `/health`).

| Endpoint | State | Tables read/written | Missing |
| --- | --- | --- | --- |
| `GET /health` | real | – | – |
| `POST /auth/dev-login` | real (dev only) | reads `auth.users` | Supabase auth; fine for now |
| `GET /auth/me` | real | `org_members`, `client_members` | – |
| `GET /clients` | **partial** | `clients` | no `is_demo` column yet; no derived stats (progress/visibility/issues/approvals) |
| `GET /clients/{id}` | real | `clients` | – |
| `POST /clients` | real | writes `clients` | no onboarding defaults (settings, brand profile stub) |
| `GET /clients/{id}/prompts` | real | `prompts` | – |
| `POST /clients/{id}/prompts` | **partial** | `prompts` | cap from `settings.billing_limits` (default 25, spec: 125); no dedupe/uniqueness; no PATCH/retire |
| `GET /clients/{id}/gaps` | real | `gaps`, `prompts` | no evidence/answers, no status transition |
| `GET /clients/{id}/metrics/daily` | real | `daily_metrics` | no page consumes it yet |
| `POST /clients/{id}/audits` | real | writes `audits`, `audit_findings`, `site_pages` | synchronous (no progress); PageSpeed missing |
| `GET /clients/{id}/audits`, `/audits/{id}` | real | reads `audits`, `audit_findings`, `site_pages` | – |
| `POST /clients/{id}/content/briefs` | **partial** | writes `content_briefs`, `approvals` | brief is an empty shell ("generation pending") — no agent, no outline, no sources |
| `GET /clients/{id}/content/approvals` | real | `approvals` | subject titles not joined |
| `POST /clients/{id}/content/approvals/{id}/action` | **partial** | `approvals` | gate exists, but nothing enforces it downstream: the publish worker does not require an approved record for the exact version |
| `POST /clients/{id}/integrations/oauth/callback` | **mock** | writes `integrations` | stubbed token exchange (`mock_acc`/`mock_ref`); **deferred scope** — must not be advertised as working |
| `GET /clients/{id}/edge/search` | **partial** | reads `content_items`, `content_versions` | real query, but needs `EDGE_SERVICE_TOKEN` (unset) and any published content |
| `POST /webhooks/stripe` | real | writes `clients.settings` | disabled unless `STRIPE_WEBHOOK_SECRET` set |

Missing endpoints for the spec: website setup checklist/summary, brand profile + aliases CRUD, brand memory ingest, competitors CRUD, personas CRUD, prompt update/retire, research agent, run collection now, collection health, prompt detail/answers, dashboard action queue, competitor matrix, brief generation, content editor/versions/diff, publish target config, publisher, refresh proposals, third-party tasks, outreach, memos, admin (users/audit log/spend/caps/re-parse/run logs).

## 4. Workers (`services/workers/app/`)

| Job | State | Tables written | Notes |
| --- | --- | --- | --- |
| `run_daily_batch` | real | `collection_batches` | fans out `collect_and_parse`; unique per (client, day) but re-runs re-enqueue |
| `collect_and_parse` | **partial** | `answers`, `answer_citations`, `domains`, `brand_mentions` | Full real pipeline (adapter → normalize → citations → mention judge). Uses **mock adapters when keys are missing** (B1); no token/cost logging; no retries/idempotency on (client, prompt, engine, day, run) beyond arq `_job_id`; `k` from `clients.settings.run_count` (default 3) |
| `finalize_daily_batches` | real | `collection_batches` | – |
| `compute_rollup_for_day` | real | `daily_metrics`, `domain_citation_daily`, `gaps` | PRD §1.7 math, tested; gaps → slipped + competitor_cited |
| `run_publisher` | **mock** | `publications`, `content_items` | The WordPress/Webflow "publish" sleeps and returns a fabricated URL. Also **no approval gate**, no encrypted credentials, no retry/idempotency, no live URL verification of the actual CMS response. |
| `verify_publication` | **partial** | `publications`, `gaps` | Real HTTP fetch of the recorded URL, but marks mapped gaps **won immediately** on 200 instead of waiting for a later collection to prove the gap closed (spec says prove-then-close). |
| `embed_publication` | **mock** | `brand_memory_chunks` | Constant vector (B2). |
| `sync_gsc_data`, `sync_ga4_data` | **mock** | `gsc_daily`, `ga4_daily`, `integrations` | Hardcoded clicks/impressions/sessions. Disabled by scope (B4) — must not run. |
| `send_weekly_digest` | **stub** | – | Sleeps and logs. |
| `runner.py` (`daily-batch` / `rollup` / `all`) | real | – | Redis-less execution path; used for local runs and the upcoming smoke test. |

`services/agents/app/graph.py` is a mock: `mock_brief_generator` / `mock_draft_generator` print and return `pending_approval`; no LangGraph, no grounding, no agent_runs accounting. There are **no agents wired to any job**.

`apps/feeds-edge` is real Worker code (KV key check → backend proxy) but unexercised: `SERVICE_TOKEN` empty, `kv_namespaces.id = "mock_kv_id"`, `BACKEND_URL = https://api.footnote.dev`, never deployed. `/portal/settings` advertises it with a fake key.

## 5. Database coverage

| Table | Status | Read by | Written by |
| --- | --- | --- | --- |
| `organizations`, `org_members`, `client_members`, `auth.users` | real | auth | seed |
| `clients` | real | clients routes, workers | clients routes, seed |
| `brand_profiles` | **unused** | – | seed only → **M1 CRUD + form** |
| `brand_aliases` | **partial** | worker (mention detection) | seed only → **M1 CRUD** |
| `competitors` | **partial** | worker (citation ownership) | seed only → **M1 CRUD** |
| `personas` | **unused** | – | seed only → **M1 CRUD** |
| `brand_memory_chunks` | **mock** | – | embedder (fake vectors) → **M1 ingest, M4 retrieval** |
| `prompts` | **partial** | list page, worker | create form, seed → M2 research agent, edit/retire |
| `collection_batches` | partial | – | worker → M2 health UI |
| `answers` | partial | – | worker → M2 detail UI |
| `domains`, `answer_citations`, `brand_mentions` | real | rollups | worker |
| `daily_metrics` | real | metrics route | rollup → M1 dashboard, M6 analytics |
| `domain_citation_daily` | real | – | rollup → M2/M6 |
| `gaps` | real | gaps page | rollup, seed |
| `site_pages`, `audits`, `audit_findings` | real | site-audit page | audit route |
| `content_briefs`, `approvals` | partial | approvals route | brief route → M4 |
| `content_items`, `content_versions`, `content_prompt_map` | **unused** | publisher reads | nothing creates them → **M4/M5** |
| `publish_targets` | **unused** | – | – → **M5** |
| `feeds_sites`, `refresh_proposals`, `third_party_tasks`, `outreach_targets`, `outreach_messages`, `memos` | **unused** | – | – → **M5/M6** |
| `publications` | mock | – | mock publisher → M5 |
| `integrations`, `gsc_*`, `ga4_*`, `leads` | **mock/deferred** | sync workers | mock sync workers → do not run |
| `agent_runs` | **unused** | – | – → **cost control, all milestones** |
| `model_release_events`, `audit_log` | **unused** | – | – → M2 / M7 |

RLS is enabled on every `client_id` table (37 policies); workers connect as the table owner and **filter by `client_id` explicitly** (they bypass RLS by design).

## 6. What "real end to end" still requires (milestone map)

| Area | Milestone |
| --- | --- |
| `is_demo` migration, derived website status + setup checklist, `/ops/websites/[id]`, brand profile + aliases CRUD, brand memory ingest, competitors/personas CRUD, header switcher as the one switcher, Dashboard action queue + portfolio summary | **M1** |
| Prompt research agent, real engine collection (keys), scheduler + caps + run-now, parser/judge golden set ≥30, collection health, Prompts/Tracking/Gaps screens | **M2** |
| Crawler rules (robots per AI bot, PageSpeed, JSON-LD validity), rule re-runs + dev brief, competitor intelligence matrix | **M3** |
| Brief generation from gaps, LangGraph content graph, editor with versions/diff/claim checks, hard approval gate | **M4** |
| Real WordPress publisher + encrypted creds, feeds static build, post-publish verification, prove-then-close gaps | **M5** |
| Refresh agent, third-party board, outreach, monthly memo, real analytics page | **M6** |
| Portal (role-gated, no mocks), Admin (users/roles/audit log/spend/caps/re-parse/run logs) | **M7** |

## 7. Verification environment as of this check

- Services: API `127.0.0.1:8000`, Next dev `0.0.0.0:3000` (both listening).
- DB (Neon): 5 clients — DBA (real), Acme Corp, Test Site, Client A, Client B (demo/test artifacts). Migrations applied: `0000_auth.sql`, `0001_init.sql`.
- Backend battery (last run): `ruff` 0 · `mypy --strict` 0/49 · `pytest` 42 passed · judge eval 100% (8/8).
- Frontend battery (last run): `tsc` 0 · eslint 0 errors · `next build` ✓.

---

## 8. Milestone 1 status update (2026-10-04)

Implemented in this pass; the tables below supersede the step-0 rows they replace.

**Now real**

| Item | What changed |
| --- | --- |
| `clients.is_demo` | Migration `0002_clients_is_demo.sql`; Acme Corp / Test Site / Client A / Client B flagged demo, hidden by default, `include_demo=true` toggle with a "Demo data" badge. |
| Website list (`/ops/websites`) | Derived status (checklist-driven; explicit paused/churned wins), setup `n/7`, last collection, visibility 7d, open issues, pending approvals, demo toggle. `/ops/clients` redirects here. |
| Website detail (`/ops/websites/[id]`) | Setup checklist with fix links, brand profile form (voice, positioning, products, ICP, proof points, banned claims, aliases, theme), brand-memory ingest + chunk list, competitors + personas CRUD with aliases, publishing "not configured" state. |
| Setup checklist + derived status | `services/api/app/website_status.py`; 7 items (brand profile, competitors, personas, 25+ prompts, baseline collection, site audit, publish target); status can no longer contradict the checklist. |
| Dashboard (`/ops`) | Real action queue + portfolio summary from `GET /clients/{id}/dashboard`: visibility/mention/link/citation-share/SOV with numerator+denominator and prior window, run counts, failed-run count, collection health, "Needs attention" (setup, failed runs, critical/high audit findings, slipped prompts, new gaps, approvals, refresh flags, stale prompts) and "Recent wins". Correlation caveat + per-metric "How this is calculated". Google data shows "Not connected. Planned."; engine providers show "None configured" when no keys exist. |
| Header website switcher | Single persisted switcher in the header (all pages), demo badge, setup progress; fixed a feedback loop where the header re-dispatched its own change event. |
| Brand memory ingestion | Real OpenAI `text-embedding-3-small` (1536-d) embeddings; without `OPENAI_API_KEY` the API returns an explicit 503 and writes nothing. Re-ingest is idempotent per (client, source, title); token/cost logged to `agent_runs`. |
| Prompt lifecycle | `PATCH /clients/{id}/prompts/{prompt_id}` (edit/retire/reactivate, sets `retired_at`), persona binding, cap now the product cap of **125** active (billing override can lower it). |
| Website status math | `visibility_pct` is a 0-1 ratio everywhere (was returned 0-100 and displayed 100x too large in the list). |

**Still stubbed / not yet real** (unchanged by this milestone)

- Engine collection still falls back to mock adapters when provider keys are missing (there are **no provider keys in `.env`**) — the dashboard now states this explicitly instead of claiming "Connected". Milestone 2 makes mock mode opt-in.
- `/ops/analytics`, `/ops/pipeline`, `/ops/admin`, all `/portal` pages: still mock; owned by Milestones 6-7.
- Publishing (`publish_targets`, WordPress, feeds), content generation, agents, refresh/off-topic work: Milestones 4-6.
- `site-audit` remains the real crawler from Sprint C; PageSpeed and per-AI-bot robots rules land in Milestone 3.

**Battery after Milestone 1** (all exit 0): `ruff` 0 · `mypy --strict` 0/39 · `pytest` **67 passed** (25 new website/API tests) · judge eval 100% (8/8) · `tsc --noEmit` 0 · eslint 0 errors (1 pre-existing warning) · `next build` ✓ (17 routes). Browser E2E: websites list with demo toggle, detail checklist/brand profile/competitors/personas CRUD, brand-memory 503 without a key, dashboard KPIs + action queue, switcher persistence, `/ops/clients` and `/` redirects.

---

## 9. Milestone 2 status update (2026-10-04)

Implemented in this pass; supersedes the M2 rows above.

**Now real**

| Item | What changed |
| --- | --- |
| Migration `0003_m2_collection.sql` | `answers.run_day/attempts/judge_version`, partial unique `answers_run_key (client_id, prompt_id, engine, run_index, run_day)`, `prompt_candidates` + RLS policy. Applied to Neon. |
| Engine adapters | Rewritten against current official APIs (verified 2026-10-04): OpenAI Chat Completions `gpt-5-search-api` + `web_search_options` (`gpt-4o-search-preview` is deprecated), Gemini `generateContent` + `google_search` grounding, Perplexity **Agent API** `POST /v1/agent` preset `fast` (Sonar Chat Completions ended 2026-09-27), xAI Responses API `grok-4.7` + `web_search` (top-level + inline citations), Anthropic Messages `claude-sonnet-5-5` + `web_search` tool. Citations are parsed per provider contract. |
| Explicit mock gating | Mock adapters only with `ALLOW_MOCK_ENGINES=true` (or runner `--mock`). Otherwise an unconfigured engine raises an actionable error: "set OPENAI_API_KEY (or ALLOW_MOCK_ENGINES=true for local runs)". Mock rows carry `raw_json.mock=true` + `-mock` model label and are counted separately in health. |
| Scheduler + idempotency | `worker.schedule_collection`: k=3 runs/prompt/engine (`clients.settings.run_count`), UTC `run_day`, jittered fan-out for cron (`collection_jitter_seconds=120`, 0 for CLI/manual), daily call cap (`billing_limits.max_daily_calls`, default 2000; over-cap inserts deleted and counted `skipped_cap`). Re-running the day is a no-op (`already_scheduled`); manual run-now adds `max(run_index)+1` per prompt/engine so raw answers are never clobbered. Retries: 3 attempts, backoff x2 ±25%, retryable 429/5xx. |
| Run now | `POST /clients/{id}/collection/run` — one prompt or whole website, schedules queued answer rows and drains an in-process queue (Redis-less). Runner CLI: `python -m services.workers.app.runner daily-batch / run-now / rollup / all` with `--client --prompt --jitter --mock`. |
| Parser + judge v2 | `rules-v2` judge: citations extraction, domain normalization + taxonomy (owned / competitor / forum / review_site / wiki / news / publisher / marketplace / gov_edu / other), alias + sentence-level fuzzy brand/competitor detection (edit-distance ≤1 for words ≥6 chars only), competitor mentions stored (`entity_kind=competitor`) driving SOV/matrix. Optional LLM judge (`judge_mode=llm`, `judge_model=gpt-5-mini`) falls back to rules and records `answers.judge_version`. Re-parse is idempotent per answer and skips already-parsed successes. |
| Golden set | 40 hand-labelled fixtures (`packages/evals/golden_set.json`); harness gates ≥95% per axis (min 30 cases) → **100% (40/40)** mention/recommendation/sentiment. |
| Research agent | `services/api/app/prompt_research.py`: seeds from brand profile/aliases, competitors, personas, site pages, existing prompts; template generator always available, LLM candidates (`gpt-5-mini`, JSON) when `OPENAI_API_KEY` is set with fallback; funnel stage + lead-intent scoring + rationale; accept (optionally edited), reject, 125-prompt cap; every run logged to `agent_runs` (tokens; USD null — no verified price table). Routes `POST /research/generate`, `GET /research/candidates?status`, accept/reject. |
| Rollups + gaps | Existing daily_metrics/domain_citation_daily/gap SQL kept and wired to real answers; gap detection (`slipped`, `competitor_cited`) now driven by collected + parsed runs. Collection health = succeeded / scheduled with failures listed (error + attempts), per engine. |
| Screens | Prompts (health panel + failures + mock badge, research panel, 14-day sparkline, per-engine dots, run-now/edit/retire, 125 counter); **Prompt detail** (`/ops/prompts/[id]`) with every run, raw answer, citations, mentions, judge/mock/latency/attempts, run-now; **Tracking** (`/ops/tracking`) with daily visibility bars, citation domains + taxonomy + share, competitor matrix; **Gaps & Slips** with status tabs, evidence drawer (why + raw answers + citations), transitions open → in_progress → won / dismissed (reopen included). |
| Bug fixes | asyncpg `:param::jsonb` casts (`CAST(... AS jsonb)`), personas `ORDER BY name`, `require_prompt_cap` nested JSONB set, queue ctx shape in run-now, health window uses `run_day`, header/demo selection: `getDefaultClientId` no longer resets a demo client selection. |

**Still stubbed / not yet real (M2 scope)**

- **No provider keys in `.env`** → live collection is impossible; every run fails with the explicit key error above (by design, visible in health). Add keys or set `ALLOW_MOCK_ENGINES=true` for a keyless demo.
- **No Redis** → the nightly cron (`worker.run_daily_batch` with jitter) needs Redis or the runner CLI on a scheduler (e.g. Windows Task Scheduler).
- Google GSC/GA4 remain deferred (tables untouched; UI "Not connected. Planned.").
- LLM judge exists but is not the default (`judge_mode=rules`); no verified per-token price table, so `agent_runs.cost` stays null.
- ROI remains own-data only with the correlation caveat.

**Battery after Milestone 2** (all exit 0): `ruff` 0 · `mypy --strict` 0/62 · `pytest` **109 passed** (16 new M2 API tests, 22 judge/parser tests) · judge eval **100% (40/40)** · `tsc --noEmit` 0 · eslint 0 errors (1 pre-existing warning) · `next build` ✓ (18 routes, incl. `/ops/prompts/[id]`, `/ops/tracking`).

**Browser E2E (2026-10-04, DBA + Acme demo)**: DBA prompts page — health empty state, "Find candidates" → 10 template candidates, accept → prompt with `research` badge, run-now → 12 runs scheduled, all failed with "set PERPLEXITY_API_KEY / XAI_API_KEY …" and per-engine 0/3 shown in health; prompt detail showed all 12→16 runs with errors, judge/mock/geo metadata; Acme gaps — 3 open gaps, evidence drawer (why + 12 raw mock answers + citations), open → in_progress → won → reopen (state restored); Acme tracking — visibility 62.9% (352/560), citation share 14.3% (60/420), SOV 60.7%, domain taxonomy table, competitor matrix; DBA tracking empty states render; switcher persistence verified (fixed a bug where demo selections were reset). Console clean (no React errors/warnings).

**Manual setup required for live collection**: add to `.env` (write-protected — edit manually): `OPENAI_API_KEY`, `GEMINI_API_KEY`, `PERPLEXITY_API_KEY`, `XAI_API_KEY` (optional `ANTHROPIC_API_KEY`), then restart the API (no `--reload`). Optional: `ALLOW_MOCK_ENGINES=true` for keyless local runs; Redis or a scheduled runner for nightly batches.
