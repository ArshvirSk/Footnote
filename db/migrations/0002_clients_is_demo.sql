-- Footnote — Milestone 1: mark demo/seeded websites so the console can hide
-- them by default and badge them as "Demo data" when shown.
--
-- A website with is_demo = true must never appear in a real client's reporting
-- views. Demo rows are only ever surfaced behind an explicit operator toggle.

alter table clients
  add column if not exists is_demo boolean not null default false;

comment on column clients.is_demo is
  'Seeded/demo website. Hidden by default in the ops console; only shown behind an explicit toggle with a "Demo data" badge.';

-- Backfill the existing seeded and fixture websites (Sprint A–D testing):
--   Acme Corp (seed script, fixed UUID), Test Site (browser E2E, example.com),
--   Client A / Client B (test fixtures, client-a.com / client-b.com).
-- Real websites (e.g. the DBA site) are untouched.
update clients
set is_demo = true
where id = '30000000-0000-0000-0000-000000000001'
   or primary_domain in ('example.com', 'client-a.com', 'client-b.com');

create index if not exists clients_org_demo_idx on clients (org_id, is_demo);
