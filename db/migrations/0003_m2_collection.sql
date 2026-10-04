-- Footnote — Milestone 2: idempotent collection scheduling, judge provenance,
-- and the research-agent candidate queue.
-- New columns/tables only; applied migrations are never edited.

-- ───────────── Answers: run key, retries, judge provenance ─────────────
-- run_day is the UTC day of the schedule; with run_index it forms the
-- idempotency key (client, prompt, engine, run_index, day).
alter table answers add column if not exists run_day date;
-- How many provider attempts the collector needed (retries included).
alter table answers add column if not exists attempts smallint not null default 0;
-- Version of the mention judge that produced brand_mentions for this answer.
alter table answers add column if not exists judge_version text;

-- Partial unique index: only M2+ scheduled rows carry run_day, so historical
-- fixture rows (NULL) can never collide with the key.
create unique index if not exists answers_run_key
  on answers (client_id, prompt_id, engine, run_index, run_day)
  where run_day is not null;

-- ───────────── Research agent candidate queue (FR-5..FR-7) ─────────────
create table if not exists prompt_candidates (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  text text not null,
  kind text not null default 'ai_prompt',
  funnel_stage text,                        -- awareness | consideration | decision
  lead_intent_score smallint check (lead_intent_score between 0 and 100),
  persona_id uuid references personas,
  rationale text,                           -- why the agent proposed it (seed inputs used)
  generator text not null,                  -- template | llm
  model text,                               -- model label when generator = llm
  status text not null default 'pending',   -- pending | accepted | rejected
  duplicate_of uuid references prompts,     -- matches an existing prompt when accepted-skip
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  accepted_prompt_id uuid references prompts on delete set null,
  check (status in ('pending', 'accepted', 'rejected'))
);
create index if not exists prompt_candidates_client_status
  on prompt_candidates (client_id, status, created_at desc);

-- RLS: same tenant policy the 0001 bootstrap applies to every client_id table.
alter table prompt_candidates enable row level security;
drop policy if exists tenant_access on prompt_candidates;
create policy tenant_access on prompt_candidates
  using (has_client_access(client_id)) with check (has_client_access(client_id));
