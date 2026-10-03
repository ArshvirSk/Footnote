-- Footnote — Postgres 15+ / Supabase schema
-- Multi-tenant: organization (operator/agency) -> clients (brands) -> everything else

create extension if not exists pgcrypto;
create extension if not exists vector;
create extension if not exists pg_trgm;

-- ───────────── Enums ─────────────
create type engine_t         as enum ('chatgpt','gemini','perplexity','claude','grok','google_aio');
create type collect_mode_t   as enum ('api','ui');
create type member_role_t    as enum ('owner','admin','strategist','editor','client_approver','client_viewer');
create type content_status_t as enum ('idea','briefed','drafting','in_review','client_review','approved','scheduled','published','refresh_needed','archived');
create type approval_status_t as enum ('pending','approved','rejected','changes_requested');
create type domain_type_t    as enum ('owned','competitor','forum','review_site','wiki','news','publisher','marketplace','gov_edu','other');
create type sentiment_t      as enum ('positive','neutral','negative','mixed');
create type job_status_t     as enum ('queued','running','succeeded','failed','skipped');

-- ───────────── Tenancy ─────────────
create table organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text unique not null,
  created_at timestamptz not null default now()
);

create table org_members (
  org_id uuid references organizations on delete cascade,
  user_id uuid not null,                       -- auth.users.id
  role member_role_t not null,
  primary key (org_id, user_id)
);

create table clients (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  name text not null,
  primary_domain text not null,
  industry text,
  country text default 'IN',
  status text not null default 'onboarding',   -- onboarding | active | paused | churned
  settings jsonb not null default '{}',        -- schedules, run_count, geo, caps
  onboarded_at timestamptz,
  created_at timestamptz not null default now()
);

create table client_members (                   -- client-portal users
  client_id uuid references clients on delete cascade,
  user_id uuid not null,
  role member_role_t not null check (role in ('client_approver','client_viewer')),
  primary key (client_id, user_id)
);

-- ───────────── Brand memory ─────────────
create table brand_profiles (
  client_id uuid primary key references clients on delete cascade,
  voice text, positioning text,
  products jsonb default '[]', icp jsonb default '{}',
  proof_points jsonb default '[]',             -- studies, certifications, stats (client-supplied)
  banned_claims text[] default '{}',
  theme_html text, theme_css text,
  updated_at timestamptz default now()
);

create table brand_aliases (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  alias text not null, is_primary boolean default false
);

create table competitors (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  name text not null, domain text,
  aliases text[] default '{}'
);

create table personas (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  name text not null, description text
);

create table brand_memory_chunks (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  source text not null,                        -- brief | asset | site | study
  title text, content text not null,
  embedding vector(1536),
  created_at timestamptz default now()
);
create index on brand_memory_chunks using hnsw (embedding vector_cosine_ops);

-- ───────────── Prompts & collection ─────────────
create table prompts (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  text text not null,
  kind text not null default 'ai_prompt',      -- ai_prompt | keyword
  persona_id uuid references personas,
  funnel_stage text,                           -- awareness | consideration | decision
  lead_intent_score smallint check (lead_intent_score between 0 and 100),
  engines engine_t[] not null default '{chatgpt,gemini,perplexity,grok}',
  source text,                                 -- gsc | llm | paa | reddit | manual
  is_active boolean default true,
  created_at timestamptz default now(),
  retired_at timestamptz
);
create index on prompts (client_id, is_active);

create table collection_batches (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  scheduled_for date not null,
  status job_status_t not null default 'queued',
  started_at timestamptz, finished_at timestamptz,
  stats jsonb default '{}',
  unique (client_id, scheduled_for)
);

create table answers (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid references collection_batches on delete cascade,
  client_id uuid not null references clients on delete cascade,
  prompt_id uuid not null references prompts,
  engine engine_t not null,
  mode collect_mode_t not null,
  run_index smallint not null default 1,       -- k-th repeat of same prompt that day
  geo text default 'IN',
  status job_status_t not null default 'queued',
  raw_text text, raw_json jsonb,
  screenshot_path text,
  model_label text,                            -- as reported/observed
  latency_ms int, error text,
  collected_at timestamptz,
  parsed_at timestamptz
);
create index on answers (client_id, prompt_id, engine, collected_at desc);

create table domains (
  id uuid primary key default gen_random_uuid(),
  domain text unique not null,
  domain_type domain_type_t default 'other',
  authority_score numeric,
  first_seen timestamptz default now()
);

create table answer_citations (
  id uuid primary key default gen_random_uuid(),
  answer_id uuid not null references answers on delete cascade,
  client_id uuid not null references clients on delete cascade,
  url text not null, title text,
  domain_id uuid references domains,
  position smallint,
  is_brand_owned boolean default false,
  competitor_id uuid references competitors
);
create index on answer_citations (client_id, domain_id);
create index on answer_citations (answer_id);

create table brand_mentions (
  id uuid primary key default gen_random_uuid(),
  answer_id uuid not null references answers on delete cascade,
  client_id uuid not null references clients on delete cascade,
  entity_kind text not null check (entity_kind in ('brand','competitor')),
  competitor_id uuid references competitors,
  rank_in_answer smallint,
  linked boolean default false,
  recommended boolean,
  sentiment sentiment_t,
  excerpt text
);
create index on brand_mentions (client_id, answer_id);

create table daily_metrics (
  client_id uuid references clients on delete cascade,
  day date, engine engine_t,
  prompts_tracked int, prompts_visible int,
  mention_rate numeric, linked_rate numeric,
  brand_citations int, total_citations int, citation_share numeric,
  share_of_voice numeric, avg_sentiment numeric,
  primary key (client_id, day, engine)
);

create table domain_citation_daily (
  client_id uuid references clients on delete cascade,
  day date, domain_id uuid references domains,
  citations int, is_brand boolean default false,
  primary key (client_id, day, domain_id)
);

create table gaps (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  prompt_id uuid references prompts,
  gap_type text not null,                      -- absent | competitor_cited | source_missing | slipped
  details jsonb default '{}',
  status text default 'open',                  -- open | in_progress | won | dismissed
  detected_at timestamptz default now(), closed_at timestamptz
);

-- ───────────── Site audit ─────────────
create table site_pages (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  url text not null, status_code int, title text,
  meta jsonb, jsonld jsonb, word_count int,
  content_hash text, last_crawled_at timestamptz,
  unique (client_id, url)
);

create table audits (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  started_at timestamptz default now(), finished_at timestamptz,
  score numeric, summary jsonb default '{}'
);

create table audit_findings (
  id uuid primary key default gen_random_uuid(),
  audit_id uuid not null references audits on delete cascade,
  client_id uuid not null references clients on delete cascade,
  category text not null,                      -- schema | meta | robots | llms_txt | sitemap | speed | entity
  severity text not null,                      -- critical | high | medium | low
  url text, rule text, detail text,
  fix_owner text default 'team',               -- team | client_dev
  status text default 'open'
);

-- ───────────── Content ─────────────
create table content_briefs (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  title text, angle text,
  outline jsonb, sources jsonb default '[]',
  created_by uuid, created_at timestamptz default now()
);

create table content_items (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  brief_id uuid references content_briefs,
  type text default 'article',                 -- article | faq | comparison | landing
  slug text, status content_status_t not null default 'idea',
  current_version_id uuid,
  publish_target_id uuid,
  published_url text, published_at timestamptz,
  last_refreshed_at timestamptz, decay_score numeric default 0,
  created_at timestamptz default now()
);

create table content_versions (
  id uuid primary key default gen_random_uuid(),
  content_item_id uuid not null references content_items on delete cascade,
  client_id uuid not null references clients on delete cascade,
  version_no int not null,
  title text, body_md text, body_html text,
  jsonld jsonb, meta jsonb,
  author_kind text not null,                   -- agent | human
  agent_run_id uuid,
  created_at timestamptz default now(),
  unique (content_item_id, version_no)
);

create table content_prompt_map (
  content_item_id uuid references content_items on delete cascade,
  prompt_id uuid references prompts on delete cascade,
  is_primary boolean default false,
  primary key (content_item_id, prompt_id)
);

create table approvals (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  subject_type text not null,                  -- brief | version | outreach | refresh | memo
  subject_id uuid not null,
  status approval_status_t default 'pending',
  requested_by uuid, reviewer_id uuid, comment text,
  requested_at timestamptz default now(), decided_at timestamptz
);

-- ───────────── Publishing & Feeds ─────────────
create table publish_targets (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  kind text not null,                          -- wordpress | webflow | shopify | ghost | feeds | webhook
  config_enc bytea,                            -- AES-256-GCM encrypted credentials
  status text default 'active'
);

create table feeds_sites (
  client_id uuid primary key references clients on delete cascade,
  mount_path text default '/feeds',
  custom_domain text, theme jsonb default '{}',
  origin_prefix text, last_build_at timestamptz
);

create table publications (
  id uuid primary key default gen_random_uuid(),
  content_item_id uuid not null references content_items on delete cascade,
  client_id uuid not null references clients on delete cascade,
  version_id uuid references content_versions,
  target_id uuid references publish_targets,
  external_id text, url text,
  status job_status_t default 'queued', error text,
  published_at timestamptz
);

create table refresh_proposals (
  id uuid primary key default gen_random_uuid(),
  content_item_id uuid not null references content_items on delete cascade,
  client_id uuid not null references clients on delete cascade,
  reason jsonb,                                -- {citation_loss, gsc_drop, stale_claims[], age_days}
  proposed_version_id uuid references content_versions,
  status text default 'pending', created_at timestamptz default now()
);

-- ───────────── Off-site work ─────────────
create table third_party_tasks (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  platform text not null,                      -- reddit | quora | forum | other
  target_url text, thread_title text,
  brief text, draft text,
  assignee uuid, status text default 'todo',
  posted_url text, due_at timestamptz
);

create table outreach_targets (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  domain_id uuid references domains,
  contact_name text, contact_email text,
  rationale text, status text default 'identified'
);

create table outreach_messages (
  id uuid primary key default gen_random_uuid(),
  target_id uuid not null references outreach_targets on delete cascade,
  client_id uuid not null references clients on delete cascade,
  subject text, body text,
  approval_id uuid references approvals,
  sent_at timestamptz, reply_status text
);

-- ───────────── Analytics sync ─────────────
create table integrations (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  provider text not null,                      -- gsc | ga4
  account_ref text, tokens_enc bytea,
  status text default 'active', last_synced_at timestamptz,
  unique (client_id, provider)
);

create table gsc_daily (
  client_id uuid references clients on delete cascade,
  day date, clicks int, impressions int, ctr numeric, position numeric,
  aio_impressions int,
  primary key (client_id, day)
);

create table gsc_query_daily (
  client_id uuid references clients on delete cascade,
  day date, query text, page text,
  clicks int, impressions int, position numeric,
  primary key (client_id, day, query, page)
) partition by range (day);
-- Default partition catches all rows; monthly partitions added via migration job
create table gsc_query_daily_default partition of gsc_query_daily default;

create table ga4_daily (
  client_id uuid references clients on delete cascade,
  day date, source text, medium text,
  sessions int, engaged_sessions int, conversions int,
  primary key (client_id, day, source, medium)
);

create table leads (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  occurred_at timestamptz not null,
  source text, landing_page text,
  attributed_content_id uuid references content_items,
  value numeric, raw jsonb
);

-- ───────────── Reporting, agents, ops ─────────────
create table memos (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients on delete cascade,
  period_start date, period_end date,
  metrics jsonb, draft_md text, final_md text,
  status text default 'draft', published_at timestamptz
);

create table agent_runs (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references clients on delete cascade,
  agent text not null,                         -- research | competitor | audit | content | publish | outreach | refresh | tracking | memo
  input jsonb, output jsonb,
  model text, tokens_in int, tokens_out int, cost_usd numeric(10,4),
  status job_status_t default 'queued',
  started_at timestamptz, finished_at timestamptz, trace_url text
);

create table model_release_events (
  id uuid primary key default gen_random_uuid(),
  engine engine_t not null, model_label text,
  detected_at timestamptz default now(), source_url text
);

create table audit_log (
  id bigserial primary key,
  org_id uuid, actor uuid, action text, entity text, entity_id uuid,
  meta jsonb, at timestamptz default now()
);

-- ───────────── RLS ─────────────
create or replace function has_client_access(cid uuid) returns boolean
language sql stable security definer as $$
  select exists (
    select 1 from clients c join org_members m on m.org_id = c.org_id
    where c.id = cid and m.user_id = auth.uid()
  ) or exists (
    select 1 from client_members cm where cm.client_id = cid and cm.user_id = auth.uid()
  );
$$;

-- Apply to every table that has a client_id column
do $$
declare r record;
begin
  for r in
    select table_name from information_schema.columns
    where table_schema = 'public' and column_name = 'client_id'
      and table_name not in ('clients')
  loop
    execute format('alter table %I enable row level security', r.table_name);
    execute format(
      'create policy tenant_access on %I using (has_client_access(client_id)) with check (has_client_access(client_id))',
      r.table_name);
  end loop;
end $$;

alter table clients enable row level security;
create policy org_clients on clients using (
  exists (select 1 from org_members m where m.org_id = clients.org_id and m.user_id = auth.uid())
  or exists (select 1 from client_members cm where cm.client_id = clients.id and cm.user_id = auth.uid())
);
-- NOTE: client_* roles should get read-only + approval-only policies in a follow-up migration;
-- the policy above is the baseline tenant boundary. Workers use the service role.