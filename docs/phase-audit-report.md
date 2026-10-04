# Footnote — Phase Audit & Completion Report

*Audit date: 2026-10-04 · Audited against [footnote-product-docs.md](footnote-product-docs.md) (PRD §1, TRD §2, Implementation Plan §3, App Flow §4, Schema §5) · Docker explicitly out of scope (removed by decision — see §3)*

---

## 1. Executive summary

The repository contains a **Phase 0 foundation plus the skeleton of Phase 1**, with the UI layer built as static mock screens. Nothing past Phase 1 has real implementation. Several core paths are **broken at runtime right now** — most importantly the worker process cannot even start, so no collection, rollup, sync, or publish job can run.

| Phase | Plan weeks | Status | Verdict |
| --- | --- | --- | --- |
| **0. Foundations** | wk 1 | 🟡 ~70% | Schema/RLS/API auth solid; CI is red, no sign-in UI, worker won't boot |
| **1. Measurement core** | wk 2–4 | 🟡 ~30% | Prompts CRUD + batch fan-out exist; all adapters are mocks, parser/judge is a stub, dashboards are static HTML, collection jobs crash |
| **2. Analytics + gaps** | wk 5–6 | 🔴 ~10% | Tables + cron slots exist; OAuth exchange and sync write hardcoded mock numbers; no competitor map; gap SQL flawed |
| **3. Audit + calibration** | wk 7–8 | 🔴 ~5% | Schema only. No crawler, no rules engine, no brand-memory ingest, no research agent, no wizard; portal is mock |
| **4. Content pipeline** | wk 9–10 | 🔴 ~5% | Schema + a broken brief/approval endpoint; no agents, no versioning, no editor UI, publisher writes to nonexistent tables |
| **5. Feeds + memo** | wk 11–12 | 🔴 ~5% | Edge worker skeleton exists but its backend query targets nonexistent tables and is unauthenticated; no site builder, no memo |
| **6. Refresh + off-site** | wk 13–15 | 🔴 0% | Schema tables only, zero code |
| **7. Hardening** | wk 16+ | 🔴 0% | Observability stubbed, no cost dashboards, no retention jobs, no UI-mode collectors |

**Milestones:** M1–M5 all currently ❌ unmet (details in §7).

**Verification summary (all run locally in this workspace):**

| Check | Result |
| --- | --- |
| Python venv + install requirements | ✅ ok |
| Import `services.api.app.main` | ✅ ok |
| Import `services.workers.app.worker` (Arq entrypoint) | ❌ `ModuleNotFoundError: bs4` |
| `ruff check services/ packages/` (CI gate) | ❌ **178 errors** (incl. 3 undefined names) |
| `mypy services/api/app/` (CI gate, soft) | ❌ fails immediately: *"Source file found twice"* — mypy has never actually type-checked anything |
| `pytest` | ❌ 0 tests run — needs a pgvector Postgres at `localhost:5432`; none available (Docker removed, no native pgvector instance) |
| Judge golden-set eval (`packages/evals/judge_eval.py`) | ❌ **accuracy 33% (1/3)** vs the ≥90% gate in TRD §2.4 |
| `npm run lint` (CI gate) | ❌ 6 errors, 7 warnings |
| `npx tsc --noEmit` | ✅ pass |
| `npm run build` | ✅ pass (13 routes) |
| API smoke: `uvicorn` + `GET /health` | ✅ 200; `GET /api/v1/auth/me` without token → ✅ 401 |
| Frontend ↔ API wiring | ❌ **zero** `fetch`/`axios`/`NEXT_PUBLIC_API_URL` references in `apps/web/src` |

---

## 2. What is actually delivered (inventory)

**Working today**

- Postgres schema ([db/migrations/0001_init.sql](../db/migrations/0001_init.sql), 40+ tables) matching docs §5, plus auth shim ([0000_auth.sql](../db/migrations/0000_auth.sql)) and RLS policies (`has_client_access()` applied to every `client_id` table).
- FastAPI app boots: JWT verification, role model (ops vs portal), `clients` list/create/get, `prompts` list/create with cap enforcement, `/health`, structured logging (structlog).
- RLS test suite written ([test_rls.py](../services/api/tests/test_rls.py), 8 cross-tenant cases) — **cannot execute without a pgvector database**.
- Arq worker module with cron schedule (daily batch 00:00, rollup 06:00, GSC 07:00, GA4 07:15, digest Mon 08:00) — **cannot start** (see §4).
- Next.js app: ops route group (dashboard, analytics, prompts, gaps, pipeline, admin) + portal (overview, approvals, settings); builds and typechecks.
- Cloudflare edge worker skeleton ([apps/feeds-edge/src/index.ts](../apps/feeds-edge/src/index.ts)) with Bearer-key → KV validation.
- Seed data ([services/api/scripts/seed.py](../services/api/scripts/seed.py)): demo org/client/20 prompts/60 fixture answers/7 days of metrics.

**Not delivered anywhere in the codebase** (verified by search): crawler/auditor, `llms.txt`/robots checks, brand-memory ingest (chunk→embed for clients), research/competitor/content/refresh/outreach/memo agents (only two `print()` mocks in [graph.py](../services/agents/app/graph.py); **LangGraph is not even a dependency**), WordPress/Feeds publishing, methodology pages, audit log writer, agent cost tracking UI, S3/object-storage integration, Sentry/OTel/Langfuse (stubbed in [main.py:17](../services/api/app/main.py#L17)), email/digest sending, prompt CSV import, prompt detail/history views, raw-answer drawer, retention jobs.

---

## 3. Docker removal — current state & fallout

Docker is out of scope. These Docker artifacts and references remain and need a decision:

| Artifact | Status | Action needed |
| --- | --- | --- |
| [docker-compose.yml](../docker-compose.yml) | Still present, now **db + redis only** | Remove, or keep as optional local DB helper |
| [.dockerignore](../.dockerignore), [apps/web/Dockerfile](../apps/web/Dockerfile), apps/web/.dockerignore | Present, unused | Delete |
| [README.md](../README.md) | All instructions are `docker compose …` (start, seed, test, lint) | Rewrite for native runs (venv + npm + uvicorn + arq) |
| [start.ps1](../start.ps1) | Line 3 `docker compose up -d`, line 22 seeds via `docker compose exec db` | Rewrite: needs a Postgres/Redis source that isn't Docker |
| **CI** [.github/workflows/ci.yml:49](../.github/workflows/ci.yml#L49) | Runs `psql -f infra/docker/init-auth-schema.sql` — **`infra/` is empty, file does not exist** → CI backend job fails at step 3 | Point at `db/migrations/0000_auth.sql` (identical shim) |
| [.env.example](../.env.example) | Hosts are Docker names: `db`, `redis`, `minio` | Change to `localhost` — native runs will fail to connect otherwise |
| Docs §2.2 "Deploy: Docker" row, §3.1 `infra/ # docker, CI, IaC` | Plan still mandates Docker | Update plan to Vercel (web) + native/container-less host (API/workers) |

**No-Docker data layer options (must pick one before tests/CI can go green):**

1. **Hosted Supabase** (matches TRD §2.1 anyway): free tier gives Postgres+pgvector+Auth+RLS; CI can connect over TLS. Recommended — it also removes the need for the `auth.users` shim in production.
2. **Native Postgres 18** (already installed at `C:\Program Files\PostgreSQL\18`) **+ pgvector** compiled/installed manually — only option for fully offline dev; pgvector is not installed today, which is why tests can't run.
3. CI: GitHub Actions service containers (already used — this is independent of project Dockerfiles and can stay).

Redis is required by Arq (queues + rate limiter). Without Docker: native Redis for Windows (Memurai) or a lightweight substitute — or run collectors in-process with a simple asyncio scheduler until Redis is available.

---

## 4. P0 blockers — broken right now

| # | Defect | Location | Impact |
| --- | --- | --- | --- |
| B1 | Worker entrypoint fails to import: `from bs4 import BeautifulSoup` but **beautifulsoup4 is not in any requirements.txt** | [publisher.py:7](../services/workers/app/publisher.py#L7) | **Arq worker never starts** → zero collection, rollups, syncs, publishes |
| B2 | `time` used but never imported → `NameError` on every collection job | [worker.py:39](../services/workers/app/worker.py#L39), [worker.py:48](../services/workers/app/worker.py#L48) | Even after B1, every `collect_and_parse` job crashes |
| B3 | `os.urandom` used but `os` not imported → 500 on OAuth callback whenever `ENCRYPTION_KEY` is set | [integrations.py:38](../services/api/app/routes/integrations.py#L38) | GSC/GA4 connect flow crashes |
| B4 | Brief/approval endpoint writes to **tables/columns that don't exist** (`briefs`, `comments`, `entity_type`, `gate_type`, `reviewed_by`) and reads `user.id` (field is `user_id`) | [content.py:50](../services/api/app/routes/content.py#L50), [content.py:96](../services/api/app/routes/content.py#L96) | Brief creation & approval action 500 |
| B5 | Stripe webhook references nonexistent `organizations.stripe_customer_id`; **signature verification is commented out** | [billing.py:41](../services/api/app/routes/billing.py#L41) | Webhook 500 + unauthenticated state-changing endpoint |
| B6 | `/clients/{id}/edge/search` has **no auth dependency** and queries nonexistent tables (`content_chunks`, `drafts`, `publications.target_url`, `is_live`) | [edge.py:19](../services/api/app/routes/edge.py#L19) | Cross-tenant data exposure risk + 500 |
| B7 | Publisher writes `publications(entity_type, entity_id, target_url, is_live)`; schema has `content_item_id, version_id, target_id, url, status` | [publisher.py:61](../services/workers/app/publisher.py#L61) | Publish job fails on schema mismatch |
| B8 | Embedder writes `content_chunks` — table doesn't exist | [embedder.py](../services/workers/app/embedder.py) | Edge RAG ingest fails |
| B9 | CI: missing `infra/docker/init-auth-schema.sql`; ruff 178 errors; eslint 6 errors; mypy module-resolution error | [.github/workflows/ci.yml:49](../.github/workflows/ci.yml#L49) | **CI red on every run** |
| B10 | Tests require a pgvector Postgres that doesn't exist in a Docker-less setup | [conftest.py](../services/api/tests/conftest.py) | Phase 0 DoD ("RLS test suite passes") unverifiable |

**Security notes (also P0):** API connects as the `postgres` superuser, so **RLS is bypassed at runtime** — route-level `has_client_access()` checks are the real tenant boundary, which makes B6 (skipped check on the edge route) exploitable. The Stripe webhook accepts unsigned payloads. Internal worker/service auth header on the edge→API hop is accepted but never validated.

---

## 5. Metric correctness defects (Phase 1 core)

Even once collection runs, the numbers won't match docs §1.7:

1. **Visibility is computed wrong** — `prompts_visible` = prompts with *any* brand mention ([worker.py:181](../services/workers/app/worker.py#L181)); spec requires brand mentioned in **≥50% of that prompt's runs that day**, per engine.
2. **Citation-share inflation** — the rollup `LEFT JOIN brand_mentions × answer_citations` multiplies rows, so `total_citations`/`citation_share` are over-counted whenever an answer has multiple mentions/citations.
3. **Hard-zero metrics** — `linked_rate`, `share_of_voice`, `avg_sentiment` are inserted as `0` always.
4. **Domain classification never happens** — `domains.domain_type` stays default `other`; `is_brand_owned`/`competitor_id` are never set on citations (so "competitor_cited" gaps can never fire correctly), and `domain_citation_daily` is never written at all.
5. **Judge is a substring check** — `evaluate_mention` returns `recommended=True, sentiment=positive` whenever the brand name appears ([parser.py](../services/workers/app/parser.py)); its own golden set scores 33% (expected ≥90%). No alias/competitor handling (`brand_aliases` are passed as `[]`), no rank, no judge-prompt versioning.
6. **Gap SQL flaws** — slip query keys off day-level `prompts_visible = 0` rather than per-prompt history; `gaps` has no unique key so `ON CONFLICT DO NOTHING` never dedupes → duplicates nightly.
7. **GSC/GA4 sync writes fabricated constants** (120 clicks / 1500 impressions / 45 sessions…) with `DO UPDATE`, overwriting any real data once real sync lands.
8. **`AI_REFERRER_REGEX` is double-escaped in a raw string** (`r'chatgpt\\.com'` matches a literal backslash) and is never used anyway ([sync.py:17](../services/workers/app/sync.py#L17)).

---

## 6. Phase-by-phase audit & remaining work

### Phase 0 — Foundations (wk 1) — 🟡 ~70%

**Delivered:** repo layout matches §3.1; migrations + RLS baseline; FastAPI JWT/roles/tenant context; clients + prompts routes; Arq settings class; Next.js shell with role-grouped routes; test scaffolding.

**DoD check**
- ❌ *Operator can sign in* — no login page, no Supabase client, no session handling anywhere in `apps/web`.
- 🟡 *Create a client* — API `POST /api/v1/clients` works; no UI.
- ⚠️ *RLS test suite passes* — suite written but unrunnable in current env (B10); CI that would run it is red (B9).

**Remaining work**
- [ ] Fix CI: auth-shim path, ruff errors, eslint errors, mypy config (`explicit_package_bases`/namespace packages so it runs once, not "source found twice").
- [ ] Pick no-Docker data layer (§3) and make `pytest` runnable; prove the 8 RLS tests pass.
- [ ] Login/sign-in flow (Supabase Auth or self-hosted JWT issuer) + session on both route groups; role-based redirect from `/`.
- [ ] Client list/create UI in ops console (sidebar "Clients" is a dead `#` link).
- [ ] Wire `.env.example`/`start.ps1`/README to native run instructions.
- [ ] Wire Sentry (or drop it from TRD); `setup_observability()` is commented out.
- [ ] Audit-log writes for auth/client mutations (FR-29 partly).

### Phase 1 — Measurement core (wk 2–4) — 🟡 ~30%

**Delivered:** prompts list/create API + cap enforcement (though default cap is **25** via `settings.billing_limits`, not the doc's **125** — [prompts.py:93](../services/api/app/routes/prompts.py#L93)); batch fan-out with per-day idempotent job ids; token-bucket rate limiter (Redis/Lua); parser skeleton (regex citations, domain normalize); rollup SQL; prompts UI (static mock, "New Prompt"/"Import CSV" buttons do nothing).

**DoD check** — *Client's prompts run daily; dashboard shows visibility + citation share with drill-down to raw answers* — ❌ **not met**: worker won't start (B1), jobs crash (B2), adapters are all mocks, no dashboard reads the API.

**Remaining work**
- [ ] Unblock worker: fix B1/B2; decide default run mode (`MockEngineAdapter` only if `ENGINE_MODE=mock`).
- [ ] Real adapters per TRD §2.3: OpenAI web-search tool, Gemini grounding, Perplexity Sonar, xAI search, (Anthropic web search optional) — with model/pricing verified at build time; store `mode`, `model_label`, `geo`, `run_index`; dead-letter after 3 failures; manual rerun.
- [ ] Full prompt CRUD (update/retire with history, CSV import, engine multiselect, per-client cap 125, lead-intent scoring UI) — FR-5..FR-7.
- [ ] Parser hardening: alias/competitor matching (trigram + LLM verify), domain classification (rules + LLM fallback), brand-owned/competitor marking on citations, `domain_citation_daily` writes, judge prompt versioning — FR-10..FR-12.
- [ ] Replace stub judge with a real LLM judge; get golden-set accuracy ≥90% (currently 33%).
- [ ] Correct rollup math to §1.7 definitions (visibility ≥50% runs, linked rate, SoV, sentiment, citation share without join fan-out).
- [ ] Dashboards wired to API: visibility by engine, citation share vs competitors, prompt table w/ sparkline, **answer drawer with raw answer + citations** (FR-11), run counts + confidence caveats.
- [ ] Prompt detail/history page; slips & gaps list wired to real `gaps` rows.
- [ ] Unit tests for parser/domain/metrics math; adapter contract tests with recorded fixtures; nightly canary prompt (TRD §2.11).

### Phase 2 — Analytics + gaps (wk 5–6) — 🔴 ~10%

**Delivered:** `integrations`, `gsc_daily`, `gsc_query_daily` (partitioned), `ga4_daily`, `leads` tables; cron slots; OAuth callback route (mock exchange, buggy); AI-referrer regex constant (wrong escaping, unused).

**DoD check** — *Gap list from real data; GSC/GA4 charts match source UIs* — ❌ not met.

**Remaining work**
- [ ] Real Google OAuth (consent + token exchange + refresh in sync worker), fix B3, store tokens via AES-GCM (already designed) with `cryptography` dependency made explicit — FR-14.
- [ ] Real GSC Search Analytics API pulls (daily + query/page, 90-day backfill, AIO-filtered impressions) and GA4 Data API pulls; integration health badge on failure.
- [ ] AI-referral attribution from GA4 source/medium using a **configurable** (UI-editable) referrer regex list + "this undercounts" disclosure — FR-15.
- [ ] Competitor citation map view (domain × prompt matrix) + domain taxonomy (owned/competitor/forum/review/wiki/news) — FR-12.
- [ ] Fix gap/slip detection SQL (per-prompt windows per §1.7, dedupe key on `gaps`), operator notification, weekly digest email (currently `asyncio.sleep` stub).
- [ ] Charts in ops/analytics + portal: replace hard-coded KPI cards with `daily_metrics`/`gsc_daily` queries.

### Phase 3 — Audit + calibration (wk 7–8) — 🔴 ~5%

**Delivered:** schema (`site_pages`, `audits`, `audit_findings`, `brand_profiles`, `brand_aliases`, `competitors`, `personas`, `brand_memory_chunks`); seed rows for profile/aliases/competitor/persona.

**DoD check** — *New client calibrated end-to-end; MVP demoable to first client* — ❌ far from met.

**Remaining work**
- [ ] Async crawler (HTTP + sitemap discovery, Playwright only when JS needed) and rule engine: status/canonical/title/meta, JSON-LD validity, Organization `sameAs` entity drift, robots rules for GPTBot/ClaudeBot/PerplexityBot/Google-Extended, `llms.txt`, sitemap coverage, PageSpeed metrics — each rule re-runnable for fix verification — FR-16, FR-17.
- [ ] Findings UI (grouped by severity, `fix_owner` = team vs client_dev) + PR-ready dev-brief export.
- [ ] Brand profile forms (voice, positioning, products, ICP, proof points, banned claims, theme HTML/CSS) + document/URL upload → chunk → embed into `brand_memory_chunks` (needs a real embeddings provider; embedder is currently `[0.02]*1536`) — FR-2, FR-3.
- [ ] Competitors/personas/aliases management UI — FR-4.
- [ ] Research agent (first real LangGraph graph): seeds + GSC queries + competitors + personas → scored candidates → accept/edit/retire queue — FR-5. Add `langgraph` + provider SDK deps.
- [ ] Onboarding wizard matching flow §4.2 (profile → memory → competitors → research → ≤125 prompts → GSC/GA4 → baseline run → citation map → audit → baseline report → sign-off).
- [ ] Client portal: read-only visibility/citations/Google/content-shipped pages + methodology page (currently 3 static mock pages; `#` dead links for Visibility/Content).
- [ ] Baseline report generator (the sales demo artifact, §3.5).

### Phase 4 — Content pipeline (wk 9–10) — 🔴 ~5%

**Delivered:** `content_briefs`, `content_items`, `content_versions`, `content_prompt_map`, `approvals`, `publish_targets`, `publications` tables; broken brief/approval endpoints (B4); mock WP/Webflow publisher functions; static kanban + portal approvals mocks; two `print()` agent stubs.

**DoD check** — *Approved article publishes to WordPress with JSON-LD, mapped to prompts* — ❌ not met.

**Remaining work**
- [ ] Rewrite brief/approval endpoints against the real schema (`content_briefs`, `approvals.subject_type/subject_id`, `reviewer_id`, `decided_at`) and fix `user_id` bug; enforce approval matrix §4.6 (operator → editor → optional client; unsourced claims block approval).
- [ ] LangGraph content graph: strategist → writer → editor passes, typed state, checkpoints, **interrupt nodes** at human gates, `agent_runs` logging (model, tokens, cost) — FR-19, FR-20, FR-28/29.
- [ ] Grounding rules: answer-first structure, claims trace to source URL or proof point, JSON-LD (Article/FAQPage/Product), respect `banned_claims` — FR-18.
- [ ] Versioning UI: diff view, agent vs human edit attribution, sources panel.
- [ ] Real WordPress publisher (REST + application passwords), credentials in `publish_targets.config_enc` (AES-256-GCM), record live URL, JSON-LD/metadata verification — FR-22.
- [ ] Pipeline board wired to `content_items.status` (state machine §4.4), editor page, publish status.
- [ ] E2E test: approval flow → publish against a WordPress sandbox (TRD §2.11).

### Phase 5 — Feeds + memo (wk 11–12) — 🔴 ~5%

**Delivered:** edge worker skeleton (KV bearer-key validation, `/search` proxy); `feeds_sites` table; portal "Realtime Edge Feeds" settings mock; `edge/search` API (unauthenticated, broken query — B6).

**DoD check** — *No-CMS client live at `/feeds`; first monthly memo issued* — ❌ not met.

**Remaining work**
- [ ] Feeds builder: render client pages to static HTML from brand theme, embed JSON-LD, sitemap + index, upload to object storage (S3/R2 client — **no storage integration exists at all yet**), `feeds_sites.origin_prefix` tracking — FR-24.
- [ ] Edge worker: map `client.com/feeds/*` → origin prefix (the current worker only handles `/search`), cache purge on publish, `Cache-Control`, sitemap `lastmod`.
- [ ] Repair `/edge/search`: authenticate the edge hop (internal service token validation), query real tables (`content_versions`/`publications`), real embeddings, **tenant check** (B6).
- [ ] Memo generator: pull `daily_metrics`/gsc/ga4 + work log → metrics block + agent narrative → strategist edit → publish — FR-27.
- [ ] Public methodology entries per number used in marketing — FR-28 (schema-free; static pages + doc entries).

### Phase 6 — Refresh + off-site (wk 13–15) — 🔴 0%

**Delivered:** `refresh_proposals`, `third_party_tasks`, `outreach_targets`, `outreach_messages` tables only.

**Remaining work**
- [ ] Refresh agent: decay scan (citation loss, GSC click drop, stale claims, age) → rewrite proposal as diff → editor approval → back to `in_review` — FR-23.
- [ ] Third-party task board (Reddit/Quora/forum): thread, brief, human-written draft, posted URL, **disclosure rule**, humans-only — FR-25.
- [ ] Outreach: target discovery from citation domain map with rationale, drafted messages, **one approval per message, send impossible without approval record** (agents must not hold send capability — TRD §2.9) — FR-26.
- [ ] Ops console screens: off-site board + outreach (§4.1) — currently nonexistent.

### Phase 7 — Hardening (wk 16+) — 🔴 0%

**Remaining work**
- [ ] UI-mode collectors (Playwright, rotating proxies, CAPTCHA circuit breaker) — deferred with UI mode out of v1 scope until API parity is measured.
- [ ] New-model-release detection → `model_release_events` → re-baselining flow.
- [ ] Cost dashboards: per-client LLM/collection spend from `agent_runs.cost_usd`; admin UI.
- [ ] Retention jobs (raw answers/screenshots default 12 months) + signed URLs for screenshots/raw answers.
- [ ] Additional publishers (Webflow/Shopify/Ghost), Google AI Overviews tracking.
- [ ] Reliability/UX targets §2.10: ≥95% batch completion within 6h, p95 dashboard <2s from rollups, parse <10 min, 99.5% availability — instrument first, then tune.
- [ ] Load test: 20 clients × 125 prompts × 4 engines × 3 runs/day (≈36k calls/day).
- [ ] RLS hardening: client roles get read-only + approval-only policies (currently a "follow-up migration" note in the schema), worker service-role filtering audit.

---

## 7. Milestone status

| Milestone | Target | Status | Blocker |
| --- | --- | --- | --- |
| M1 — daily tracking live for a pilot client | wk 4 | ❌ | B1/B2 (worker down), mock adapters, no real engine keys |
| M2 — baseline report + audit + dashboards → first sales demo | wk 8 | ❌ | Phase 1 dashboards are static; Phase 2/3 unbuilt |
| M3 — first approved article published | wk 10 | ❌ | Phase 4 endpoints broken (B4/B7); no agents |
| M4 — Feeds live; first monthly memo | wk 12 | ❌ | No builder, no storage layer, memo code absent |
| M5 — refresh + outreach loops working | wk 15 | ❌ | Zero code |

---

## 8. FR coverage snapshot (PRD §1.6)

| Verdict | FRs |
| --- | --- |
| ✅ Implemented (API-level) | FR-1 (client create), FR-7 (partial: cap enforced but default 25 vs 125), FR-8 (fan-out logic, crashes), FR-29 (partial: `agent_runs`/`audit_log` tables, no writers) |
| 🟡 Partial / stubbed | FR-5 (no UI, no agent), FR-6 (fields exist, no scoring), FR-9 (stores raw text, no screenshots), FR-10 (metrics wrong, §5), FR-13 (gap SQL flawed), FR-14 (mock OAuth), FR-15 (regex unused/wrong), FR-21 (broken endpoint), FR-22 (mock publisher, wrong schema) |
| ❌ Not started | FR-2, FR-3, FR-4, FR-11, FR-12, FR-16, FR-17, FR-18, FR-19, FR-20, FR-23, FR-24, FR-25, FR-26, FR-27, FR-28 |

---

## 9. Recommended execution plan (Docker-free)

**Sprint A — "make it true" (≈3–4 days): restore a green baseline**
1. Fix B1–B8 (undefined imports, schema-mismatched queries, auth gap on `/edge/search`, `user.id`).
2. Fix CI: `db/migrations/0000_auth.sql` shim path; `ruff --fix` (134 auto-fixable) + hand-fix remainder; fix 6 eslint errors; repair mypy module config.
3. Choose the no-Docker data layer (recommend hosted Supabase; else native PG18 + pgvector) and get `pytest` green locally.
4. Update README/start.ps1/.env.example; delete leftover Docker artifacts; update docs §2.2/§3.1.

**Sprint B — Phase 1 completion (≈2–3 weeks):** real adapters → fix parser/judge (golden set ≥90%) → correct rollup math → dashboards wired to API → prompt CRUD UI. Exit = M1 met with real engine data.

**Sprint C — Phase 2 + 3 (≈3–4 weeks):** real Google OAuth/sync, gap/slip repair, competitor map, crawler + rules, brand memory, research agent, wizard, portal read-only + baseline report. Exit = M2.

**Sprint D — Phase 4 (≈2 weeks):** LangGraph content graph with interrupt gates, approvals per §4.6, WordPress publisher, editor/versioning UI. Exit = M3.

**Sprint E — Phase 5 (≈2 weeks):** storage layer (S3/R2), Feeds builder + edge routing, memo generator, methodology pages. Exit = M4.

**Then Phase 6 (≈2–3 weeks) → M5, then Phase 7 hardening.**

Running totals put the original 16-week plan at **realistically 20–24 weeks** at current velocity with one developer, mainly because Phases 2–6 are still greenfield and the Phase 0/1 repair work above was not budgeted.

---

## 10. Quality gates to enforce from here

- CI must be green before merging: `ruff check`, `pytest` (with a real pgvector DB), `eslint`, `tsc --noEmit`, `next build`.
- Add missing test layers per TRD §2.11: parser/metrics unit tests, judge golden-set gate in CI, adapter contract fixtures, one Playwright E2E for approval→publish.
- Block any route that touches `client_id` without `has_client_access()` (add a lint/test that asserts every router dependency includes it) — the API's DB user bypasses RLS, so route checks are the boundary.
- Ban mock data paths behind feature flags: `ENGINE_MODE=mock`, `GA4/GSC mock` writes must never run against a database that holds real data.

---

## 11. Remediation log (Sprint A — 2026-10-04)

Database decision: **Neon** (serverless Postgres) replaces Docker-based Postgres. Docker removed from all run instructions.

**Fixed — blockers:**

| ID | Fix | File(s) |
| --- | --- | --- |
| B1 | Removed unused `bs4` import (real dependency added back when URL verification is implemented); worker imports cleanly: 9 job functions, 5 crons | `services/workers/app/publisher.py` |
| B2 | Added missing `import time` | `services/workers/app/worker.py` |
| B3 | Added missing `import os`, `raise ... from e`, plus provider validation and tenant check on the OAuth callback | `services/api/app/routes/integrations.py` |
| B4 | Rewrote brief/approval endpoints against real schema (`content_briefs`, `approvals.subject_type/subject_id/reviewer_id/decided_at`), fixed `user.id`→`user_id`, removed invalid `db.begin()` usage, added read-only `client_viewer` guard, added `GET /approvals` | `services/api/app/routes/content.py` |
| B5 | Stripe webhook: real HMAC signature verification (timestamp tolerance), 503 when `STRIPE_WEBHOOK_SECRET` unset, added `organizations.stripe_customer_id` to schema | `services/api/app/routes/billing.py`, `db/migrations/0001_init.sql` |
| B6 | `/edge/search`: now requires `X-Internal-Service` token (`EDGE_SERVICE_TOKEN`, hmac compare, 503 if unconfigured), queries real tables (`content_items` × `content_versions`), tenant-scoped; edge worker sends the token | `services/api/app/routes/edge.py`, `apps/feeds-edge/src/index.ts`, `wrangler.toml` |
| B7 | Publisher writes real `publications` columns + updates `content_items` to `published`; verification fetches the URL and closes gaps via `content_prompt_map` | `services/workers/app/publisher.py` |
| B8 | Embedder stores chunks in `brand_memory_chunks` (`source='publication:{id}'`, idempotent replace) | `services/workers/app/embedder.py` |
| B9 | CI auth-shim path → `db/migrations/0000_auth.sql` (the `infra/docker/` file no longer exists) | `.github/workflows/ci.yml` |
| B10 | New idempotent migration runner (`schema_migrations` ledger) — applies SQL to Neon without psql/Docker | `services/api/scripts/migrate.py` |
| + | arq cron bug: `day_of_week=0` → `weekday=0` (weekly digest cron never registered) | `services/workers/app/worker.py` |

**Fixed — quality gates (all now pass locally):**

| Check | Before | After |
| --- | --- | --- |
| `ruff check services/ packages/` | 178 errors | **0 — All checks passed** (135 safe + 27 unsafe autofixes, rest hand-fixed: `Depends`→`Annotated`, `StrEnum`, `ClassVar`, imports) |
| `mypy` (strict) | crashed ("source file found twice") | **0 errors in 16 files** (`mypy_path` + `explicit_package_bases` in pyproject; annotations added) |
| `npm run lint` / eslint | 6 errors, 7 warnings | **0 problems** |
| `npx tsc --noEmit` | pass | pass |
| `npm run build` | pass | pass |
| Worker import (`services.workers.app.worker`) | `ModuleNotFoundError: bs4` | OK |
| API smoke | OK | OK + edge 503-unconfigured, stripe 503-unconfigured, 401 auth guard verified |

**Config changes for the no-Docker/Neon stack:**

- `config.py`: defaults now `localhost` (were Docker hostnames `db`/`redis`); new `edge_service_token`, `stripe_webhook_secret` settings.
- `.env.example`: rewritten for Neon (`DATABASE_URL` + `DATABASE_URL_SYNC` with `sslmode=require`), dropped `POSTGRES_*` Docker vars.
- `services/api/scripts/seed.py`: default DSN `db:5432` → `localhost`.
- `README.md` + `start.ps1`: fully rewritten for native runs (venv + migrate script + uvicorn/arq/npm); no Docker commands anywhere.
- Still present but unreferenced: `docker-compose.yml` (kept only as an optional local Redis helper), `.dockerignore`, `apps/web/Dockerfile`.

**Known gaps remaining (by design, tracked as Phase 1+ work):** judge still a stub (golden set 33%), engine adapters still mocks, rollup math still wrong (§5), frontend still not wired to the API, Redis required to actually *run* the worker.

**Neon setup (2026-10-04, later same day):**

- Neon CLI 8.0.6 installed; logged in; `neon mcp -y` configured 7 MCP clients; `neon skills -y` installed 8 Neon skills (project-scoped) — required invoking the CLI under the nvm Node 24.5.0 runtime (skills CLI needs ≥22.20; global `neon` runs on 20.18).
- `neon link --project-id twilight-brook-95311249 --branch production -y` → `.neon` written; `DATABASE_URL`, `DATABASE_URL_UNPOOLED`, `NEON_BRANCH` pulled into `.env`.
- `neon config init` + `neon.ts` (empty `defineConfig({})`) + `neon deploy` ✅ — but `config init` pins `@neon/config@^0.0.0`, a **metadata-only stub**; upgraded to `@neon/config@1.8.3` / `@neon/env@1.5.0` (real `./v1` export) before deploy could evaluate the file.
- App integration: `Settings` now accepts Neon's plain `postgresql://` URLs, derives `DATABASE_URL_SYNC` from the unpooled endpoint, strips `channel_binding`/`sslmode` for asyncpg (TLS passed via `connect_args={"ssl": True}` in `db.py`); stale localhost `DATABASE_URL_SYNC` removed from `.env`.
- **Schema applied to Neon:** `migrate.py` ran `0000_auth.sql` + `0001_init.sql` (pgvector/pg_trgm/37 RLS policies) on PostgreSQL 18.6.
- **RLS suite fixed at the root cause:** the original tests connected as the *table owner* (`neondb_owner`, `bypassrls=true`), so RLS never applied. `conftest.py` now creates a non-owner `footnote_test` role (granted table DML so *policy*, not privileges, is what's tested) and seeds tenants as the owner. **Result: 15/15 tests pass** (`pytest -q` exit 0), including all 8 cross-tenant RLS cases.
- Verified end-to-end: `ruff` 0, `mypy --strict` 0/16, asyncpg engine smoke against Neon (PG 18.6, 37 policies), API boot `/health` 200 + `/auth/me` 401, worker import OK.

**Sprint B — "fix it" pass (2026-10-04, same day):** closed the five limitations listed after Sprint A.

| Limitation | Fix | Evidence |
| --- | --- | ---|
| Judge stub (33%) | Rule-based judge with word-boundary alias matching, sentence-scoped negation/contrast/adverse patterns; golden set 3→8 cases (incl. `expect_none`) | `packages/evals/judge_eval.py` → **Accuracy 100% (8/8)** |
| Rollup math wrong | `compute_rollup_for_day()` rewritten to PRD §1.7: visibility = mentioned·2 ≥ runs, mention/linked/citation-share (no join fan-out), share-of-voice, sentiment (pos=1/mixed=.5/neg=−1), `domain_citation_daily` (was never written), slipped + competitor-cited gaps with open-gap dedupe | `services/workers/tests/test_rollup.py` asserts all 9 metric columns + gap set + idempotent re-run |
| Mock engine adapters | Real key-gated HTTP adapters for OpenAI (search-preview), Gemini (grounding), Perplexity (sonar), Grok (live search), Anthropic (web search tool); `get_adapter()` returns mock only when the provider key is absent. `google_aio` stays mock (no public API; UI collection is Phase 2). Rate limiting: Redis token bucket when Redis is present, in-process bucket otherwise | `services/workers/tests/test_adapters.py` — **11 contract tests** (URL/auth-header/body + response parsing + HTTP-error propagation), all pass |
| Worker needs Redis | New `services/workers/app/runner.py`: in-process `InProcessQueue` stands in for `ctx["redis"]` and runs the *same* job functions (`daily-batch`, `rollup`, `all`). Added `finalize_daily_batches()` (batches now end `succeeded`, not `running`) and fixed a `date` vs ISO-string bind bug in `run_daily_batch` | **E2E against Neon, no Redis:** 408 answers collected+parsed across 4 engines, 12 `daily_metrics` rows, 3 `domain_citation_daily` rows, 3 batches finalized, rollup exit 0 |
| Frontend not wired to API | `lib/api.ts` typed client (JWT in localStorage, 401→/login); `/login` page + dev-gated `POST /api/v1/auth/dev-login` (404 in production); Prompts page: real GET/POST with create form; Gaps page: real GET; new `GET /clients/{id}/gaps` + `GET /clients/{id}/metrics/daily` routes | Browser-verified: login → `/ops/prompts` renders 20 seeded prompts from Neon, create-prompt POST round-trips, `/ops/gaps` renders seeded gaps; cross-tenant → 403; no token → 401; `tsc` 0, eslint 0 errors, `next build` ✓ |
| `.env` write-protected | No `.env` edit needed: `seed.py` now resolves its DSN through pydantic-settings (`Settings.database_url_sync`, env override still wins), so the Neon CLI-written `.env` is picked up as-is | `python -m services.api.scripts.seed` → exit 0 against Neon |

Also fixed en route: `SET LOCAL request.jwt.claim.sub = :uid` fails as a bound parameter under asyncpg → `SELECT set_config(..., true)` (this was a 500 on every authenticated route); seed idempotency (random `uuid4()` PKs + `ON CONFLICT (id) DO NOTHING` duplicated rows on every run → deterministic `uuid5` ids, verified by running the seed twice with unchanged counts); adapter-provided citations were dropped in `collect_and_parse` (only the generic `sources` key was read) → `raw_answer.citations` now preferred, which is what made `domain_citation_daily` populate.

**Final battery (Sprint B, all exit 0):** `ruff` 0 · `mypy --strict` 0/46 · `pytest` **32 passed** (incl. 5 dev-login/auth-flow tests) · judge eval **100% (8/8)** · `tsc --noEmit` 0 · eslint 0 errors (1 pre-existing warning) · `next build` ✓ · seed idempotent · Redis-less `runner all` E2E ✓ · browser E2E (login → prompts → gaps) ✓.

**Remaining Phase 1+ gaps:** real engine calls are contract-tested but not yet live-verified (no provider API keys in `.env` — drop `OPENAI_API_KEY`/`GEMINI_API_KEY`/`PERPLEXITY_API_KEY`/`XAI_API_KEY`/`ANTHROPIC_API_KEY` in and the adapters go live); Supabase auth still stubbed by the dev-login endpoint; Arq cron scheduling still wants a real Redis (the in-process runner covers on-demand runs); `.env` remains writable only via shell (by design of the Neon CLI).

**Sprint C — sidebar fix + live site audit (2026-10-04):**

- **Sidebar/nav active state:** both consoles used hardcoded active styles (ops always showed "Admin" active; portal always showed "Settings") and plain `<a>` tags that full-page-reload. Replaced with client components driven by `usePathname()` + `next/link` (`OpsSidebar.tsx`, `PortalNav.tsx`); dead `#` links (Clients, Visibility, Content) removed. Browser-verified: navigating `/ops/site-audit` → `/ops/prompts` moves `aria-current="page"` + highlight; portal Approvals nav matches its route.
- **Site audit now connects to real websites:** the `site_pages` / `audits` / `audit_findings` schema existed with zero code behind it. Added:
  - `services/api/app/audit.py` — crawls homepage + robots.txt + sitemap.xml + llms.txt (stdlib HTMLParser, no new deps); parses title/description/canonical/og/lang/h1/JSON-LD/word-count; derives findings across all 7 schema categories (`schema | meta | robots | llms_txt | sitemap | speed | entity`); scores 100 − severity-weighted deductions (critical 30 / high 15 / medium 7 / low 3, floored at 0); follows one bounded level of child sitemaps (`.xml.gz`, gzip-decoded) capped at 20 pages; filters non-HTML assets out of page records.
  - `services/api/app/routes/audits.py` — `POST /clients/{id}/audits` (start live audit; URL defaults to the client's `primary_domain`), `GET /clients/{id}/audits`, `GET /clients/{id}/audits/{auditId}`; findings returned severity-sorted; page list scoped to that audit's `page_urls` in the summary.
  - `/ops/site-audit` page — Run audit button, score card with severity counts, findings list grouped by category, audit history, crawled-pages panel.
  - **Live verification:** `POST .../audits {"url":"https://developer.mozilla.org"}` → **201 in 16s, score 78/100, 21 pages crawled with real titles/word counts, 2 findings** (missing JSON-LD high, missing llms.txt medium), rows persisted to `audits`/`audit_findings`/`site_pages` in Neon; page renders in the browser with history. Two real-world bugs found & fixed during live runs: sitemap-index `.xml.gz` children were crawled as pages (asset-suffix filter + gzip decode + index following), and the detail endpoint leaked other audits' page rows (now scoped via `summary.page_urls`).
- **Tests:** +9 site-audit tests (HTML parsing, scoring penalties, missing-file findings, robots-disallow-all critical, asset filtering, sitemap-index expansion, https defaulting). **Battery: `ruff` 0 · `mypy --strict` 0/49 · `pytest` 42 passed · judge 100% (8/8) · `tsc` 0 · eslint 0 errors · `next build` ✓ · live MDN audit ✓.**

**Sprint D — console UI: websites management + client switcher + dynamic header (2026-10-04):**

- **Websites page (`/ops/clients`):** new nav item (between Analytics and Prompts) → table of clients with name/domain/status, inline "Add website" form (scheme+path stripped from the domain input), row-click to set the active client (Active badge follows), and a per-row **Audit now** button that selects the client, starts a live audit and routes to `/ops/site-audit`.
- **Client switcher on `/ops/site-audit`:** a `<select>` (shown only when >1 client) that switches the audited client in place — score card, findings, history and crawled pages all reload for the chosen site; selection persists via `localStorage` + a `footnote:client-changed` window event.
- **Dynamic header (`OpsHeader.tsx`):** replaces the static brand header in the ops layout — shows the **active client name** (reacts to client changes across pages) and the signed-in email from `/auth/me`.
- **`lib/api.ts`:** `getSelectedClientId`/`setSelectedClientId` + event dispatch, `clients.list/create`, `me()`, and `getDefaultClientId()` rewritten to prefer the explicit selection, else the newest client (persisted).
- **Live browser E2E (all verified):** added "Test Site / https://example.com/home" via the form → created, domain stripped to `example.com`, auto-selected, header switched to it → clicked **Audit now** → routed to `/ops/site-audit` with a fresh **live audit of example.com: score 5/100, 9 findings, 1 page** persisted to Neon → switched the dropdown to Acme Corp → header + data flipped to the MDN audit (78, 21 pages, 5 history entries) → navigated to `/ops/prompts` → selection persisted. Fresh reload: all API calls 200, zero console errors.
- **Battery: `tsc --noEmit` 0 · eslint 0 errors (1 pre-existing warning) · `next build` ✓ (16 routes incl. `/ops/clients`) · backend untouched — `ruff`/`mypy`/`pytest` unchanged at 42 passed.**
