-- Migration 0011: Milestone 10 Search Analytics Engine, AI Referral Attribution & GSC Sync
-- Ensures fast rollups for GSC/GA4 and tracks real-time integration sync telemetry.

-- 1. Ensure indexes for high-speed GSC & GA4 analytics rollups
CREATE INDEX IF NOT EXISTS idx_gsc_daily_client_day
  ON gsc_daily (client_id, day DESC);

CREATE INDEX IF NOT EXISTS idx_gsc_query_daily_client_query
  ON gsc_query_daily (client_id, query);

CREATE INDEX IF NOT EXISTS idx_ga4_daily_client_source
  ON ga4_daily (client_id, day DESC, source);

-- 2. Add sync status and configuration metadata to integrations
ALTER TABLE integrations
  ADD COLUMN IF NOT EXISTS sync_status text DEFAULT 'idle',
  ADD COLUMN IF NOT EXISTS sync_error text,
  ADD COLUMN IF NOT EXISTS config jsonb NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_integrations_client_provider
  ON integrations (client_id, provider);
