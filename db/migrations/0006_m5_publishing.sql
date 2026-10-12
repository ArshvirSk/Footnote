-- M5: Publishing engine, verification, and gap lifecycle schema additions
-- Depends on: 0001_init.sql, 0005_m4_content.sql

-- ─── publish_targets: metadata, status, and testing ───
ALTER TABLE publish_targets
  ADD COLUMN IF NOT EXISTS name text,
  ADD COLUMN IF NOT EXISTS is_default boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS last_tested_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_test_status text DEFAULT 'untested',
  ADD COLUMN IF NOT EXISTS last_test_error text,
  ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now(),
  ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();

-- ─── publications: metadata & verification details ───
ALTER TABLE publications
  ADD COLUMN IF NOT EXISTS title text,
  ADD COLUMN IF NOT EXISTS jsonld_verified boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS canonical_verified boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS http_status int,
  ADD COLUMN IF NOT EXISTS verified_at timestamptz,
  ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();

-- ─── gaps: prove-then-close lifecycle linkage ───
ALTER TABLE gaps
  ADD COLUMN IF NOT EXISTS published_content_id uuid REFERENCES content_items(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS verified_at timestamptz;

-- ─── Indexes for publishing queries ───
CREATE INDEX IF NOT EXISTS idx_publish_targets_client ON publish_targets (client_id, status);
CREATE INDEX IF NOT EXISTS idx_publications_client_content ON publications (client_id, content_item_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_publications_status ON publications (client_id, status);
CREATE INDEX IF NOT EXISTS idx_gaps_published ON gaps (client_id, status) WHERE status = 'verified_published';
