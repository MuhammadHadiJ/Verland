-- Supports the move from a direct psycopg/superuser DB connection to
-- Supabase's PostgREST REST/RPC API (see main.py). Two things this closes:
--
-- 1. property_reviews had no DELETE policy. Delete "worked" only because the
--    old connection used the postgres superuser role, which bypasses RLS
--    entirely -- the policy set never actually ran. Going through PostgREST
--    means RLS is enforced for real, so the missing policy would silently
--    break review deletion without this.
-- 2. The five functions below replace hand-built SQL that used to live in
--    main.py (spatial batch queries, city-alias search, proximity dedup) --
--    PostgREST can only call stored functions for anything beyond simple
--    table filters, so this logic has to live here now instead.
--
-- All are `language sql stable` with no SECURITY DEFINER, matching the
-- existing exact_property_reviews / nearby_area_observations functions --
-- they run as the calling role, so RLS on the underlying tables still
-- applies (e.g. anon/authenticated both only ever see public, active
-- reviews, same as today).

create policy "Review authors can delete their reviews"
on public.property_reviews for delete
to authenticated
using (user_id = auth.uid());

-- Replaces the dynamic WHERE-clause building in handle_list_properties().
create or replace function public.search_properties(
  search_query text default null,
  city_aliases text[] default null,
  origin_lat double precision default null,
  origin_lng double precision default null,
  radius_m double precision default null
)
returns table (
  id uuid,
  name text,
  property_type public.property_type,
  address text,
  area text,
  city text,
  country text,
  latitude double precision,
  longitude double precision,
  external_provider text,
  external_place_id text,
  external_display_name text,
  google_place_id text,
  google_place_name text,
  google_formatted_address text,
  map_provider text,
  created_by uuid,
  verified_at timestamptz,
  created_at timestamptz,
  updated_at timestamptz,
  distance_m double precision
)
language sql
stable
as $$
  select
    p.id, p.name, p.property_type, p.address, p.area, p.city, p.country,
    p.latitude, p.longitude, p.external_provider, p.external_place_id,
    p.external_display_name, p.google_place_id, p.google_place_name,
    p.google_formatted_address, p.map_provider, p.created_by, p.verified_at,
    p.created_at, p.updated_at,
    case when origin_lat is not null and origin_lng is not null
      then st_distance(p.location, st_setsrid(st_makepoint(origin_lng, origin_lat), 4326)::geography)
    end as distance_m
  from public.properties p
  where
    (search_query is null or search_query = '' or (
      lower(p.name) like '%' || lower(search_query) || '%'
      or lower(p.address) like '%' || lower(search_query) || '%'
      or lower(p.area) like '%' || lower(search_query) || '%'
      or lower(coalesce(p.external_display_name, '')) like '%' || lower(search_query) || '%'
    ))
    and (city_aliases is null or lower(p.city) = any(city_aliases))
    and (
      origin_lat is null or origin_lng is null or radius_m is null
      or st_dwithin(p.location, st_setsrid(st_makepoint(origin_lng, origin_lat), 4326)::geography, radius_m)
    )
  order by
    case when origin_lat is not null and origin_lng is not null
      then st_distance(p.location, st_setsrid(st_makepoint(origin_lng, origin_lat), 4326)::geography)
    end asc nulls last,
    p.created_at desc
  limit 50;
$$;

-- Replaces the second query in handle_get_property() / handle_neighbourhood_preview()
-- -- reviews of any property within radius_m of a point, for neighbourhood
-- aggregation (not tied to one property_id).
create or replace function public.nearby_property_reviews(
  lat double precision,
  lng double precision,
  radius_m integer default 250
)
returns setof public.property_reviews
language sql
stable
as $$
  select r.*
  from public.property_reviews r
  join public.properties p on r.property_id = p.id
  where st_dwithin(p.location, st_setsrid(st_makepoint(lng, lat), 4326)::geography, radius_m)
    and r.visibility = 'public'
    and r.moderation_status = 'active';
$$;

-- Replaces the first query in batch_fetch_reviews() -- all reviews for a
-- list of properties (list view), in one call instead of N.
create or replace function public.batch_reviews_for_properties(property_ids uuid[])
returns table (
  id uuid,
  property_id uuid,
  user_id uuid,
  contributor_role public.contributor_role,
  lived_period text,
  rent_range text,
  hidden_costs text,
  comment text,
  electricity smallint,
  water smallint,
  gas smallint,
  building_maintenance smallint,
  elevator smallint,
  parking smallint,
  standby_power smallint,
  noise smallint,
  security smallint,
  cleanliness smallint,
  traffic smallint,
  flooding smallint,
  created_at timestamptz,
  reviewer_name text
)
language sql
stable
as $$
  select
    r.id, r.property_id, r.user_id, r.contributor_role,
    r.lived_period, r.rent_range, r.hidden_costs, r.comment,
    r.electricity, r.water, r.gas, r.building_maintenance,
    r.elevator, r.parking, r.standby_power,
    r.noise, r.security, r.cleanliness, r.traffic, r.flooding,
    r.created_at,
    pr.display_name as reviewer_name
  from public.property_reviews r
  left join public.profiles pr on r.user_id = pr.id
  where r.property_id = any(property_ids)
    and r.visibility = 'public'
    and r.moderation_status = 'active'
  order by r.created_at desc;
$$;

-- Replaces the second query in batch_fetch_reviews() -- the VALUES-list
-- lateral join that fetched neighbourhood reviews for every property in a
-- list in one query. anchors is a jsonb array of {"id","lat","lng"} objects
-- (PostgREST RPC has no clean way to pass parallel arrays, so a jsonb blob
-- is the standard pattern here). Only returns the fields neighbourhood
-- aggregation actually reads (NEIGHBORHOOD_FIELDS in main.py).
create or replace function public.batch_nearby_reviews(anchors jsonb, radius_m integer default 250)
returns table (
  anchor_id uuid,
  noise smallint,
  security smallint,
  cleanliness smallint,
  traffic smallint,
  flooding smallint
)
language sql
stable
as $$
  select
    (ref->>'id')::uuid as anchor_id,
    r.noise, r.security, r.cleanliness, r.traffic, r.flooding
  from jsonb_array_elements(anchors) as ref
  join public.property_reviews r on true
  join public.properties p on r.property_id = p.id
  where st_dwithin(
      p.location,
      st_setsrid(st_makepoint((ref->>'lng')::double precision, (ref->>'lat')::double precision), 4326)::geography,
      radius_m
    )
    and r.visibility = 'public'
    and r.moderation_status = 'active';
$$;

-- Replaces the proximity-match fallback in handle_create_review() -- find
-- an existing property within radius_m when there's no external_place_id
-- match, so a review doesn't create a duplicate property.
create or replace function public.find_property_by_location(
  lat double precision,
  lng double precision,
  radius_m double precision default 20
)
returns setof public.properties
language sql
stable
as $$
  select p.*
  from public.properties p
  where st_dwithin(p.location, st_setsrid(st_makepoint(lng, lat), 4326)::geography, radius_m)
  order by st_distance(p.location, st_setsrid(st_makepoint(lng, lat), 4326)::geography) asc
  limit 1;
$$;
