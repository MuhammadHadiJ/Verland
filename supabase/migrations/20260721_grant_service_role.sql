-- The project originally granted table privileges only to anon/authenticated
-- (the app used those roles exclusively). Once admin property editing started
-- going through the service-role/sb_secret key, writes failed with
-- "42501 permission denied for table properties" because service_role had no
-- grants on the public schema. service_role bypasses RLS and is only reachable
-- via the secret key server-side, so granting it full access is the standard
-- Supabase configuration.

grant usage on schema public to service_role;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant all on all functions in schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;
alter default privileges in schema public grant all on functions to service_role;
