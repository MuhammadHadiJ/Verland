# Supabase Backend

Run `schema.sql` in the Supabase SQL editor for the Pakistan MVP backend.

The schema creates:

- `profiles` for future account types and trust states
- `properties` with PostGIS geography points for exact real estate selection
- provider-neutral `external_provider` / `external_place_id` metadata, with lat/lng as the portable source of truth
- `property_reviews` tied directly to one exact property
- `area_observations` for nearby shared factors like street noise or security
- `property_claims` so owner/landlord restrictions can be added later
- `review_access_grants` as a future contribution-to-view window
- `nearby_properties(lat, lng, radius_m)` for map click lookup
- `nearby_area_observations(lat, lng, radius_m)` for shared context
- Row-level security policies for public reads and authenticated writes

Recommended local env names:

```text
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<public anon key>
SUPABASE_PROJECT_REF=<project-ref>
SUPABASE_DB_PASSWORD=<database password>
LOCATIONIQ_API_KEY=<LocationIQ key>
GOOGLE_MAPS_API_KEY=<optional future browser Maps JavaScript API key>
```

The current Python prototype also accepts the existing `Project_Ref` and `DB_Password` names, but `KEY=value` format is safer for local tooling.
