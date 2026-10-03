-- Seed data for Footnote Demo
INSERT INTO organizations (name, slug) VALUES ('Acme Corp', 'acme-corp') ON CONFLICT DO NOTHING;

INSERT INTO auth.users (id, email) 
VALUES ('00000000-0000-0000-0000-000000000001', 'admin@acme.com') 
ON CONFLICT DO NOTHING;

DO $$
DECLARE
    org_id uuid;
BEGIN
    SELECT id INTO org_id FROM organizations WHERE name = 'Acme Corp';
    
    INSERT INTO org_members (org_id, user_id, role)
    VALUES (org_id, '00000000-0000-0000-0000-000000000001', 'owner')
    ON CONFLICT DO NOTHING;

    INSERT INTO clients (org_id, name, primary_domain)
    VALUES (org_id, 'Acme AI Software', 'acme.ai')
    ON CONFLICT DO NOTHING;
END $$;
