-- Fix #12: This migration added external_provider columns as a provider-agnostic
-- replacement for the old google_* columns. The backfill UPDATE below had a
-- no-op self-reference (coalesce(external_place_id, ...) where external_place_id
-- is already null by definition on new rows). It is harmless but documented here
-- for clarity. No logic change — columns were already correct after the ALTER.

alter table public.properties
  add column if not exists external_provider text not null default 'manual',
  add column if not exists external_place_id text,
  add column if not exists external_display_name text,
  add column if not exists external_payload jsonb;

-- Backfill: copy google_* fields into external_* for any pre-existing rows
-- that were created with the old google provider.
-- NOTE: coalesce(external_place_id, google_place_id) here means:
--   "use google_place_id only if external_place_id is still null"
-- which is the correct intent for a one-time backfill.
update public.properties
set
  external_provider     = coalesce(nullif(map_provider, ''), 'manual'),
  external_place_id     = coalesce(external_place_id, google_place_id),
  external_display_name = coalesce(external_display_name, google_place_name, google_formatted_address)
where external_provider = 'manual'
  and (google_place_id is not null or google_place_name is not null or google_formatted_address is not null);

update public.properties
set map_provider = 'locationiq'
where map_provider = 'google'
  and google_place_id is null;

create index if not exists properties_external_provider_place_idx
  on public.properties (external_provider, external_place_id)
  where external_place_id is not null;

-- Fix #15: nearby_properties() SQL function removed.
-- It was defined here but never called by the application — main.py builds
-- the spatial query inline via batch_fetch_reviews(). Keeping a dead function
-- in the schema creates confusion about what the actual query path is.
-- The function is dropped in migration 20260622_cleanup.sql.
