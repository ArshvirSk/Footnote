-- Milestone 6: Content Refresh, Off-Site Authority, Outreach, Memos, Analytics
-- Enhances existing tables with indexes, timestamps, and supplementary columns.

-- ───────────── 1. Content Refresh Enhancements ─────────────
-- content_items already has decay_score and last_refreshed_at (0001_init);
-- add the scan timestamp so the refresh cron can track when it last evaluated.
ALTER TABLE content_items
  ADD COLUMN IF NOT EXISTS last_scanned_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_content_items_decay
  ON content_items (client_id, status, decay_score DESC);

-- refresh_proposals: add diff summary, reviewer tracking
ALTER TABLE refresh_proposals
  ADD COLUMN IF NOT EXISTS diff_summary text,
  ADD COLUMN IF NOT EXISTS reviewer_id uuid,
  ADD COLUMN IF NOT EXISTS decided_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_refresh_proposals_client
  ON refresh_proposals (client_id, status);

-- ───────────── 2. Third-Party Tasks Enhancements ─────────────
ALTER TABLE third_party_tasks
  ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now(),
  ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_third_party_tasks_client
  ON third_party_tasks (client_id, status, due_at);

-- ───────────── 3. Digital PR & Outreach Enhancements ─────────────
ALTER TABLE outreach_targets
  ADD COLUMN IF NOT EXISTS citation_frequency int DEFAULT 0,
  ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_outreach_targets_client
  ON outreach_targets (client_id, status);

ALTER TABLE outreach_messages
  ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();

-- ───────────── 4. Executive Memos Enhancements ─────────────
ALTER TABLE memos
  ADD COLUMN IF NOT EXISTS title text,
  ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now(),
  ADD COLUMN IF NOT EXISTS reviewer_id uuid;

CREATE INDEX IF NOT EXISTS idx_memos_client
  ON memos (client_id, status, period_end DESC);

-- ───────────── 5. Analytics Support Indexes ─────────────
-- Accelerate the 30/90-day time-series aggregations used by the analytics API.
CREATE INDEX IF NOT EXISTS idx_daily_metrics_client_day
  ON daily_metrics (client_id, day DESC);

CREATE INDEX IF NOT EXISTS idx_brand_mentions_entity
  ON brand_mentions (client_id, entity_kind);

CREATE INDEX IF NOT EXISTS idx_answer_citations_brand
  ON answer_citations (client_id, is_brand_owned);

CREATE INDEX IF NOT EXISTS idx_gaps_status
  ON gaps (client_id, status, closed_at DESC);

CREATE INDEX IF NOT EXISTS idx_publications_client
  ON publications (client_id, status, published_at DESC);
