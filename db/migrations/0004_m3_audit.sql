-- Milestone 3: rule re-runs (fix verification), finding triage and dev briefs.
--
-- Findings are rule-coded snapshots attached to one audit. Re-running an audit
-- re-crawls the same site and compares snapshots by (rule, url):
--   * a finding that vanished is marked fixed + verified_at + resolved_in_audit_id
--   * a finding that is still present keeps its status (open/in_progress) and
--     gets last_seen_at = now()
--   * an ignored finding stays ignored (operator triage wins)
-- The dev brief is generated from the latest snapshot; suggested_fix stores the
-- PR-ready remediation text per finding so exports are deterministic.

alter table audit_findings
  add column if not exists suggested_fix text,
  add column if not exists first_seen_at timestamptz default now(),
  add column if not exists last_seen_at timestamptz default now(),
  add column if not exists verified_at timestamptz,
  add column if not exists resolved_in_audit_id uuid references audits(id) on delete set null;

alter table audits
  add column if not exists rerun_of uuid references audits(id) on delete set null;

create index if not exists audit_findings_client_rule_idx on audit_findings (client_id, rule);
