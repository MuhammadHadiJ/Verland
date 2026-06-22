-- DANGER: This will delete EVERYTHING in the public schema of your Supabase database.
-- Run this in the Supabase SQL Editor to get a clean slate.

drop schema if exists public cascade;
create schema public;

-- Standard Supabase permissions
grant usage on schema public to postgres, anon, authenticated, service_role;
grant all privileges on all tables in schema public to postgres, anon, authenticated, service_role;
grant all privileges on all functions in schema public to postgres, anon, authenticated, service_role;
grant all privileges on all sequences in schema public to postgres, anon, authenticated, service_role;

-- Re-enable extensions
create extension if not exists "pgcrypto" with schema public;
create extension if not exists "postgis" with schema public;

-- Custom Types
create type public.property_type as enum (
  'apartment',
  'house',
  'plot',
  'commercial'
);

create type public.account_kind as enum (
  'resident',
  'buyer_or_tenant',
  'owner_or_landlord',
  'general_public',
  'moderator',
  'admin'
);

create type public.contributor_role as enum (
  'current_resident',
  'former_resident',
  'buyer_or_tenant_prospect',
  'general_public_contributor',
  'owner_or_landlord'
);

create type public.claim_status as enum (
  'pending',
  'approved',
  'rejected',
  'revoked'
);

create type public.review_visibility as enum (
  'public',
  'contributor_only',
  'hidden'
);

create type public.moderation_status as enum (
  'active',
  'flagged',
  'removed'
);

create type public.area_observation_kind as enum (
  'noise',
  'street_security',
  'cleanliness',
  'air_quality',
  'road_access',
  'transport',
  'other'
);

-- Tables
create table public.profiles (
  id uuid primary key, -- references auth.users(id) in a real setup
  display_name text,
  account_kind public.account_kind not null default 'general_public',
  is_trusted boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.properties (
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
  created_by uuid, -- references auth.users(id)
  verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint properties_country_pakistan check (country = 'Pakistan'),
  constraint properties_latitude_check check (latitude between 23.0 and 38.0),
  constraint properties_longitude_check check (longitude between 60.0 and 78.0)
);

create table public.property_claims (
  id uuid primary key default gen_random_uuid(),
  property_id uuid not null references public.properties(id) on delete cascade,
  user_id uuid not null, -- references auth.users(id)
  claimed_role text not null,
  status public.claim_status not null default 'pending',
  evidence_note text,
  reviewed_by uuid, -- references auth.users(id)
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (property_id, user_id, claimed_role)
);

create table public.property_reviews (
  id uuid primary key default gen_random_uuid(),
  property_id uuid not null references public.properties(id) on delete cascade,
  user_id uuid, -- references auth.users(id)
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
  -- Ternary fields: Good=5 / Fair=3 / Poor=1 (or field-specific equivalents)
  electricity          smallint not null check (electricity          in (1, 3, 5)),
  water                smallint not null check (water                in (1, 3, 5)),
  gas                  smallint not null check (gas                  in (1, 3, 5)),
  building_maintenance smallint not null check (building_maintenance in (1, 3, 5)),
  structure            smallint not null check (structure            in (1, 3, 5)),
  seepage              smallint not null check (seepage              in (1, 3, 5)),
  mobile_signal        smallint not null check (mobile_signal        in (1, 3, 5)),
  noise                smallint not null check (noise                in (1, 3, 5)),
  security             smallint not null check (security             in (1, 3, 5)),
  cleanliness          smallint not null check (cleanliness          in (1, 3, 5)),
  road_access          smallint not null check (road_access          in (1, 3, 5)),
  traffic              smallint not null check (traffic              in (1, 3, 5)),
  flooding             smallint not null check (flooding             in (1, 3, 5)),
  sewage               smallint not null check (sewage               in (1, 3, 5)),
  -- Binary fields: Present/Available=5 / Not Present/Not Available=1
  elevator             smallint not null check (elevator             in (1, 5)),
  internet             smallint not null check (internet             in (1, 5)),
  parking              smallint not null check (parking              in (1, 5)),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.area_observations (
  id uuid primary key default gen_random_uuid(),
  anchor_property_id uuid references public.properties(id) on delete set null,
  user_id uuid, -- references auth.users(id)
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

create index properties_location_idx on public.properties using gist (location);
create index property_reviews_property_id_created_at_idx on public.property_reviews (property_id, created_at desc);
create index area_observations_location_idx on public.area_observations using gist (location);
create index properties_external_provider_place_idx on public.properties (external_provider, external_place_id)
  where external_place_id is not null;

-- One review per user per property (anonymous rows excluded)
alter table public.property_reviews
  add constraint property_reviews_one_per_user_per_property
  unique nulls not distinct (property_id, user_id);

-- Helper functions for V1 Refined Logic
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger profiles_set_updated_at before update on public.profiles for each row execute function public.set_updated_at();
create trigger properties_set_updated_at before update on public.properties for each row execute function public.set_updated_at();
create trigger property_reviews_set_updated_at before update on public.property_reviews for each row execute function public.set_updated_at();

-- Auto-create a profiles row whenever a new Supabase auth user signs up
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, display_name, account_kind)
  values (
    new.id,
    coalesce(
      new.raw_user_meta_data->>'full_name',
      new.raw_user_meta_data->>'name',
      split_part(new.email, '@', 1)
    ),
    'general_public'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Note: Row Level Security (RLS) is intentionally omitted here for the MVP reset to ensure
-- the developer can immediately store data. Enable it when ready for production.
alter table public.profiles disable row level security;
alter table public.properties disable row level security;
alter table public.property_reviews disable row level security;
alter table public.area_observations disable row level security;

-- Insert a Mock User for testing if needed
-- insert into public.profiles (id, display_name, account_kind)
-- values ('00000000-0000-0000-0000-000000000000', 'Explorer User', 'general_public');
