-- Migration 0009: Milestone 8 Production Hardening & System Automation

-- 1. Index model_release_events for fast lookups by engine & detection time
CREATE INDEX IF NOT EXISTS idx_model_release_engine_detected
  ON model_release_events (engine, detected_at DESC);

-- 2. Add last_baselined_at timestamp to prompts to track model drift and re-baselining
ALTER TABLE prompts
  ADD COLUMN IF NOT EXISTS last_baselined_at timestamptz;

-- 3. Index answers for data retention pruning and status scans
CREATE INDEX IF NOT EXISTS idx_answers_collected_status
  ON answers (collected_at, status);
