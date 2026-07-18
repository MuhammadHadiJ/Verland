-- Add dedicated columns for the OpenStreetMap object id/type of the place a
-- property was created from.
--
-- Why: (osm_type, osm_id) is a STABLE key for matching a LocationIQ autocomplete
-- result against an already-registered property, so the search dropdown can swap
-- LocationIQ's raw name for the curated `name`. LocationIQ/Nominatim `place_id`
-- is NOT stable across their data re-imports; osm_id is the OSM-native id and
-- survives them. Matching on osm_id (never on the name string, which is the
-- mutable field being corrected) is the reliable approach.
--
-- Existing rows are backfilled from the raw response already saved in
-- external_payload, so no LocationIQ calls are needed.

alter table public.properties
  add column if not exists external_osm_id text,
  add column if not exists external_osm_type text;

update public.properties
set external_osm_id = external_payload->>'osm_id',
    external_osm_type = external_payload->>'osm_type'
where external_payload ? 'osm_id'
  and external_osm_id is null;
