-- Migration 0008: Admin audit logging and agent run query acceleration

-- 1. Index audit_log for fast admin filtering
CREATE INDEX IF NOT EXISTS idx_audit_log_org_at
  ON audit_log (org_id, at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_actor
  ON audit_log (actor, at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_entity
  ON audit_log (entity, entity_id);

-- 2. Index agent_runs for spend rollups and monitoring
CREATE INDEX IF NOT EXISTS idx_agent_runs_client_started
  ON agent_runs (client_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_started
  ON agent_runs (agent, started_at DESC);

-- 3. Ensure client_members has index for user queries
CREATE INDEX IF NOT EXISTS idx_client_members_user
  ON client_members (user_id);
