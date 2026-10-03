-- Minimal auth schema shim for local development.
-- In production this is provided by Supabase's GoTrue service.
-- We create just enough for has_client_access() and RLS policies to work.

CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text,
  raw_user_meta_data jsonb DEFAULT '{}',
  created_at timestamptz DEFAULT now()
);

-- auth.uid() returns the current user id from the JWT claim set via
-- SET LOCAL request.jwt.claim.sub = '<uuid>';
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE
AS $$
  SELECT COALESCE(
    current_setting('request.jwt.claim.sub', true)::uuid,
    '00000000-0000-0000-0000-000000000000'::uuid
  );
$$;
