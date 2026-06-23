-- Real Estate Reality - Pakistan MVP
-- Source of truth for the Supabase/Postgres backend.

create extension if not exists "pgcrypto";
create extension if not exists "postgis";

do $$
begin
  if not exists (select 1 from pg_type where typname = 'property_type') then
    create type public.property_type as enum (
      'apartment',
      'house',
      'plot',
      'commercial'
    );
  end if;

  if not exists (select 1 from pg_type where typname = 'account_kind') then
    create type public.account_kind as enum (
      'resident',
      'buyer_or_tenant',
      'owner_or_landlord',
      'general_public',
      'moderator',
      'admin'
    );
  end if;

  if not exists (select 1 from pg_type where typname = 'contributor_role') then
    create type public.contributor_role as enum (
      'current_resident',
      'former_resident',
      'buyer_or_tenant_prospect',
      'general_public_contributor',
      'owner_or_landlord'
    );
  end if;

  if not exists (select 1 from pg_type where typname = 'claim_status') then
    create type public.claim_status as enum (
      'pending',
      'approved',
      'rejected',
      'revoked'
    );
  end if;

  if not exists (select 1 from pg_type where typname = 'review_visibility') then
    create type public.review_visibility as enum (
      'public',
      'contributor_only',
      'hidden'
    );
  end if;

  if not exists (select 1 from pg_type where typname = 'moderation_status') then
    create type public.moderation_status as enum (
      'active',
      'flagged',
      'removed'
    );
  end if;

  if not exists (select 1 from pg_type where typname = 'area_observation_kind') then
    create type public.area_observation_kind as enum (
      'noise',
      'street_security',
      'cleanliness',
      'air_quality',
      'road_access',
      'transport',
      'other'
    );
  end if;
end
$$;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  account_kind public.account_kind not null default 'general_public',
  is_trusted boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Robust migration to ensure all columns exist even if tables were created previously
do $$
begin
  -- Properties columns
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'properties' and column_name = 'external_provider') then
    alter table public.properties add column external_provider text not null default 'manual';
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'properties' and column_name = 'external_place_id') then
    alter table public.properties add column external_place_id text;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'properties' and column_name = 'external_display_name') then
    alter table public.properties add column external_display_name text;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'properties' and column_name = 'external_payload') then
    alter table public.properties add column external_payload jsonb;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'properties' and column_name = 'map_provider') then
    alter table public.properties add column map_provider text not null default 'locationiq';
  end if;

  -- Property Reviews columns
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'property_reviews' and column_name = 'noise') then
    alter table public.property_reviews add column noise smallint not null default 3 check (noise between 1 and 5);
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'property_reviews' and column_name = 'security') then
    alter table public.property_reviews add column security smallint not null default 3 check (security between 1 and 5);
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'property_reviews' and column_name = 'cleanliness') then
    alter table public.property_reviews add column cleanliness smallint not null default 3 check (cleanliness between 1 and 5);
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'property_reviews' and column_name = 'road_access') then
    alter table public.property_reviews add column road_access smallint not null default 3 check (road_access between 1 and 5);
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'property_reviews' and column_name = 'parking') then
    alter table public.property_reviews add column parking smallint not null default 3 check (parking between 1 and 5);
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'property_reviews' and column_name = 'traffic') then
    alter table public.property_reviews add column traffic smallint not null default 3 check (traffic between 1 and 5);
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'property_reviews' and column_name = 'flooding') then
    alter table public.property_reviews add column flooding smallint not null default 3 check (flooding between 1 and 5);
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'property_reviews' and column_name = 'sewage') then
    alter table public.property_reviews add column sewage smallint not null default 3 check (sewage between 1 and 5);
  end if;
end
$$;

create table if not exists public.properties (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  property_type public.property_type not null,
  address text not null,
  area text not null,
  city text not null,
  country text not null default 'Pakistan',
  latitude double precision not null,
  longitude double precision not null,
  location geography(point, 4326)
    generated always as (st_setsrid(st_makepoint(longitude, latitude), 4326)::geography) stored,
  external_provider text not null default 'manual',
  external_place_id text,
  external_display_name text,
  external_payload jsonb,
  google_place_id text,
  google_place_name text,
  google_formatted_address text,
  map_provider text not null default 'locationiq',
  created_by uuid references auth.users(id) on delete set null,
  verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint properties_country_pakistan check (country = 'Pakistan'),
  constraint properties_latitude_check check (latitude between 23.0 and 38.0),
  constraint properties_longitude_check check (longitude between 60.0 and 78.0)
);

create table if not exists public.property_claims (
  id uuid primary key default gen_random_uuid(),
  property_id uuid not null references public.properties(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  claimed_role text not null,
  status public.claim_status not null default 'pending',
  evidence_note text,
  reviewed_by uuid references auth.users(id) on delete set null,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (property_id, user_id, claimed_role)
);

create table if not exists public.property_reviews (
  id uuid primary key default gen_random_uuid(),
  property_id uuid not null references public.properties(id) on delete cascade,
  user_id uuid references auth.users(id) on delete set null,
  contributor_role public.contributor_role not null,
  lived_period text,
  occupancy_started_on date,
  occupancy_ended_on date,
  rent_range text,
  hidden_costs text,
  comment text,
  visibility public.review_visibility not null default 'public',
  moderation_status public.moderation_status not null default 'active',
  owner_claim_id uuid references public.property_claims(id) on delete set null,
  electricity smallint not null check (electricity between 1 and 5),
  water smallint not null check (water between 1 and 5),
  gas smallint not null check (gas between 1 and 5),
  building_maintenance smallint not null check (building_maintenance between 1 and 5),
  elevator smallint not null check (elevator between 1 and 5),
  structure smallint not null check (structure between 1 and 5),
  seepage smallint not null check (seepage between 1 and 5),
  internet smallint not null check (internet between 1 and 5),
  mobile_signal smallint not null check (mobile_signal between 1 and 5),
  noise smallint not null check (noise between 1 and 5) default 3,
  security smallint not null check (security between 1 and 5) default 3,
  cleanliness smallint not null check (cleanliness between 1 and 5) default 3,
  road_access smallint not null check (road_access between 1 and 5) default 3,
  parking smallint not null check (parking between 1 and 5) default 3,
  traffic smallint not null check (traffic between 1 and 5) default 3,
  flooding smallint not null check (flooding between 1 and 5) default 3,
  sewage smallint not null check (sewage between 1 and 5) default 3,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.area_observations (
  id uuid primary key default gen_random_uuid(),
  anchor_property_id uuid references public.properties(id) on delete set null,
  user_id uuid references auth.users(id) on delete set null,
  observation_kind public.area_observation_kind not null,
  severity smallint not null check (severity between 1 and 5),
  note text,
  latitude double precision not null,
  longitude double precision not null,
  location geography(point, 4326)
    generated always as (st_setsrid(st_makepoint(longitude, latitude), 4326)::geography) stored,
  visible_radius_m integer not null default 250 check (visible_radius_m between 25 and 2000),
  moderation_status public.moderation_status not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint area_observations_latitude_check check (latitude between 23.0 and 38.0),
  constraint area_observations_longitude_check check (longitude between 60.0 and 78.0)
);

create table if not exists public.review_reports (
  id uuid primary key default gen_random_uuid(),
  review_id uuid not null references public.property_reviews(id) on delete cascade,
  reporter_id uuid references auth.users(id) on delete set null,
  reason text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.review_access_grants (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  property_id uuid references public.properties(id) on delete cascade,
  granted_by_review_id uuid references public.property_reviews(id) on delete set null,
  expires_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists properties_location_idx on public.properties using gist (location);
create index if not exists properties_city_idx on public.properties (lower(city));
create index if not exists properties_google_place_id_idx on public.properties (google_place_id)
  where google_place_id is not null;
create index if not exists properties_external_provider_place_idx
  on public.properties (external_provider, external_place_id)
  where external_place_id is not null;
create index if not exists property_claims_property_user_idx
  on public.property_claims (property_id, user_id, status);
create index if not exists property_reviews_property_id_created_at_idx
  on public.property_reviews (property_id, created_at desc);
create index if not exists property_reviews_user_id_idx on public.property_reviews (user_id);
create index if not exists area_observations_location_idx on public.area_observations using gist (location);
create index if not exists area_observations_anchor_property_idx
  on public.area_observations (anchor_property_id, created_at desc);
create index if not exists review_access_grants_user_property_idx
  on public.review_access_grants (user_id, property_id);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'profiles_set_updated_at') then
    create trigger profiles_set_updated_at
    before update on public.profiles
    for each row execute function public.set_updated_at();
  end if;

  if not exists (select 1 from pg_trigger where tgname = 'properties_set_updated_at') then
    create trigger properties_set_updated_at
    before update on public.properties
    for each row execute function public.set_updated_at();
  end if;

  if not exists (select 1 from pg_trigger where tgname = 'property_claims_set_updated_at') then
    create trigger property_claims_set_updated_at
    before update on public.property_claims
    for each row execute function public.set_updated_at();
  end if;

  if not exists (select 1 from pg_trigger where tgname = 'property_reviews_set_updated_at') then
    create trigger property_reviews_set_updated_at
    before update on public.property_reviews
    for each row execute function public.set_updated_at();
  end if;

  if not exists (select 1 from pg_trigger where tgname = 'area_observations_set_updated_at') then
    create trigger area_observations_set_updated_at
    before update on public.area_observations
    for each row execute function public.set_updated_at();
  end if;
end
$$;

create or replace function public.exact_property_reviews(property_uuid uuid)
returns setof public.property_reviews
language sql
stable
as $$
  select r.*
  from public.property_reviews r
  where r.property_id = property_uuid
    and r.visibility = 'public'
    and r.moderation_status = 'active'
  order by r.created_at desc;
$$;

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
  external_display_name text,
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
    p.external_display_name,
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

create or replace function public.nearby_area_observations(
  lat double precision,
  lng double precision,
  radius_m integer default 500
)
returns table (
  id uuid,
  anchor_property_id uuid,
  observation_kind public.area_observation_kind,
  severity smallint,
  note text,
  latitude double precision,
  longitude double precision,
  visible_radius_m integer,
  distance_m double precision,
  created_at timestamptz
)
language sql
stable
as $$
  select
    o.id,
    o.anchor_property_id,
    o.observation_kind,
    o.severity,
    o.note,
    o.latitude,
    o.longitude,
    o.visible_radius_m,
    st_distance(o.location, st_setsrid(st_makepoint(lng, lat), 4326)::geography) as distance_m,
    o.created_at
  from public.area_observations o
  where o.moderation_status = 'active'
    and st_dwithin(o.location, st_setsrid(st_makepoint(lng, lat), 4326)::geography, least(radius_m, o.visible_radius_m))
  order by distance_m asc, o.created_at desc;
$$;

alter table public.profiles enable row level security;
alter table public.properties enable row level security;
alter table public.property_claims enable row level security;
alter table public.property_reviews enable row level security;
alter table public.area_observations enable row level security;
alter table public.review_reports enable row level security;
alter table public.review_access_grants enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'profiles' and policyname = 'Profiles are publicly readable') then
    create policy "Profiles are publicly readable"
    on public.profiles for select
    using (true);
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'profiles' and policyname = 'Users can insert their profile') then
    create policy "Users can insert their profile"
    on public.profiles for insert
    to authenticated
    with check (id = auth.uid());
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'profiles' and policyname = 'Users can update their profile') then
    create policy "Users can update their profile"
    on public.profiles for update
    to authenticated
    using (id = auth.uid())
    with check (id = auth.uid());
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'properties' and policyname = 'Anyone can read properties') then
    create policy "Anyone can read properties"
    on public.properties for select
    using (true);
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'properties' and policyname = 'Authenticated users can create properties') then
    create policy "Authenticated users can create properties"
    on public.properties for insert
    to authenticated
    with check (created_by = auth.uid());
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'properties' and policyname = 'Property creators can update their properties') then
    create policy "Property creators can update their properties"
    on public.properties for update
    to authenticated
    using (created_by = auth.uid())
    with check (created_by = auth.uid());
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'property_claims' and policyname = 'Users can read their own property claims') then
    create policy "Users can read their own property claims"
    on public.property_claims for select
    to authenticated
    using (user_id = auth.uid());
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'property_claims' and policyname = 'Users can create their own property claims') then
    create policy "Users can create their own property claims"
    on public.property_claims for insert
    to authenticated
    with check (user_id = auth.uid());
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'property_reviews' and policyname = 'Anyone can read public active reviews') then
    create policy "Anyone can read public active reviews"
    on public.property_reviews for select
    using (visibility = 'public' and moderation_status = 'active');
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'property_reviews' and policyname = 'Authenticated users can create reviews') then
    create policy "Authenticated users can create reviews"
    on public.property_reviews for insert
    to authenticated
    with check (user_id = auth.uid());
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'property_reviews' and policyname = 'Review authors can update their reviews') then
    create policy "Review authors can update their reviews"
    on public.property_reviews for update
    to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'area_observations' and policyname = 'Anyone can read active area observations') then
    create policy "Anyone can read active area observations"
    on public.area_observations for select
    using (moderation_status = 'active');
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'area_observations' and policyname = 'Authenticated users can create area observations') then
    create policy "Authenticated users can create area observations"
    on public.area_observations for insert
    to authenticated
    with check (user_id = auth.uid());
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'review_reports' and policyname = 'Authenticated users can report reviews') then
    create policy "Authenticated users can report reviews"
    on public.review_reports for insert
    to authenticated
    with check (reporter_id = auth.uid());
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'review_access_grants' and policyname = 'Users can read their review access grants') then
    create policy "Users can read their review access grants"
    on public.review_access_grants for select
    to authenticated
    using (user_id = auth.uid());
  end if;
end
$$;
