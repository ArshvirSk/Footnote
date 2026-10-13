-- Migration 0010: Milestone 9 Enterprise Artifact Storage & Executive Reports

-- 1. Add storage metadata and artifact paths to answers
ALTER TABLE answers
  ADD COLUMN IF NOT EXISTS storage_key text,
  ADD COLUMN IF NOT EXISTS screenshot_storage_key text;

-- 2. Add executive report cache/history table
CREATE TABLE IF NOT EXISTS executive_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  generated_by uuid REFERENCES auth.users(id),
  title text NOT NULL,
  report_type text NOT NULL DEFAULT 'visibility_audit',
  metrics_summary jsonb NOT NULL DEFAULT '{}',
  content_html text,
  storage_url text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_executive_reports_client
  ON executive_reports (client_id, created_at DESC);
