alter table public.properties
  add column if not exists external_provider text not null default 'manual',
  add column if not exists external_place_id text,
  add column if not exists external_display_name text,
  add column if not exists external_payload jsonb;

update public.properties
set
  external_provider = coalesce(nullif(map_provider, ''), 'manual'),
  external_place_id = coalesce(external_place_id, google_place_id),
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

create or replace function public.nearby_properties(
  lat double precision,
  lng double precision,
  radius_m integer default 75
)
returns table (
  id uuid,
  name text,
  property_type public.property_type,
  address text,
  area text,
  city text,
  latitude double precision,
  longitude double precision,
  google_place_id text,
  external_provider text,
  external_place_id text,
  review_count bigint,
  distance_m double precision
)
language sql
stable
as $$
  select
    p.id,
    p.name,
    p.property_type,
    p.address,
    p.area,
    p.city,
    p.latitude,
    p.longitude,
    p.google_place_id,
    p.external_provider,
    p.external_place_id,
    count(r.id) filter (
      where r.visibility = 'public' and r.moderation_status = 'active'
    ) as review_count,
    st_distance(p.location, st_setsrid(st_makepoint(lng, lat), 4326)::geography) as distance_m
  from public.properties p
  left join public.property_reviews r on r.property_id = p.id
  where st_dwithin(p.location, st_setsrid(st_makepoint(lng, lat), 4326)::geography, radius_m)
  group by p.id
  order by distance_m asc, review_count desc;
$$;
