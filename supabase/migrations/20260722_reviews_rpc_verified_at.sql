-- Bug: the "Verified resident" badge never showed even on approved reviews.
-- Cause: property reviews are fetched via the batch_reviews_for_properties RPC,
-- whose RETURNS TABLE(...) column list was defined before verified_at existed,
-- so the function silently dropped the column (the value was correct in the
-- table; the RPC just never selected it). Recreated with verified_at included.
-- (A DROP is required because changing the RETURNS TABLE shape changes the
-- function's return type.)

drop function if exists public.batch_reviews_for_properties(uuid[]);

create function public.batch_reviews_for_properties(property_ids uuid[])
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
  verified_at timestamptz,
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
    r.verified_at,
    pr.display_name as reviewer_name
  from public.property_reviews r
  left join public.profiles pr on r.user_id = pr.id
  where r.property_id = any(property_ids)
    and r.visibility = 'public'
    and r.moderation_status = 'active'
  order by r.created_at desc;
$$;
