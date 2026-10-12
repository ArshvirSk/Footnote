-- M4: Content pipeline schema additions
-- Depends on: 0001_init.sql (content_briefs, content_items, content_versions,
--             content_prompt_map, approvals, publish_targets, publications)

-- ─── content_briefs: link to gap(s) and track generation state ───
ALTER TABLE content_briefs
  ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS gap_ids uuid[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS target_prompts jsonb DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS grounding_rules jsonb DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS agent_run_id uuid REFERENCES agent_runs(id);

-- ─── content_items: ensure brief linkage is present ───
-- (brief_id already exists from 0001_init)

-- ─── content_versions: add claim-check results ───
ALTER TABLE content_versions
  ADD COLUMN IF NOT EXISTS claims jsonb DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS word_count int,
  ADD COLUMN IF NOT EXISTS reading_time_min numeric;

-- ─── brief-to-prompt mapping (which prompts/gaps a brief targets) ───
CREATE TABLE IF NOT EXISTS content_brief_prompts (
  brief_id uuid NOT NULL REFERENCES content_briefs(id) ON DELETE CASCADE,
  prompt_id uuid NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
  PRIMARY KEY (brief_id, prompt_id)
);

-- RLS on content_brief_prompts
ALTER TABLE content_brief_prompts ENABLE ROW LEVEL SECURITY;
CREATE POLICY content_brief_prompts_tenant ON content_brief_prompts
  USING (
    brief_id IN (SELECT id FROM content_briefs WHERE client_id IN (
      SELECT client_id FROM client_members WHERE user_id = auth.uid()
      UNION
      SELECT c.id FROM clients c JOIN org_members om ON om.org_id = c.org_id WHERE om.user_id = auth.uid()
    ))
  );

-- ─── Index for pipeline queries ───
CREATE INDEX IF NOT EXISTS idx_content_items_status ON content_items (client_id, status);
CREATE INDEX IF NOT EXISTS idx_content_items_brief ON content_items (brief_id) WHERE brief_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_content_versions_item ON content_versions (content_item_id, version_no DESC);
CREATE INDEX IF NOT EXISTS idx_approvals_pending ON approvals (client_id, status) WHERE status = 'pending';
