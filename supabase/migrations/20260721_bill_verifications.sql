-- Verification system, step 1: storage + data model for utility-bill verification.
--
-- A resident uploads a utility bill proving they live/own at a property; it lands
-- in a PRIVATE storage bucket (backend-only, via the service role) and creates a
-- pending row here. An admin views it via a short-lived signed URL, approves or
-- rejects, and the bill is deleted on decision. Approval stamps verified_at on the
-- reviewer's review -> "Verified resident" badge.

-- Private bucket for utility bills (no public access).
insert into storage.buckets (id, name, public)
values ('bills', 'bills', false)
on conflict (id) do nothing;

create table if not exists public.bill_verifications (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  property_id   uuid not null references public.properties(id) on delete cascade,
  review_id     uuid references public.property_reviews(id) on delete set null,
  evidence_path text not null,
  status        text not null default 'pending' check (status in ('pending','approved','rejected')),
  submitted_note text,
  reviewed_by   uuid references auth.users(id) on delete set null,
  reviewed_at   timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

alter table public.bill_verifications enable row level security;

do $$ begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='bill_verifications' and policyname='Users can create their own verification') then
    create policy "Users can create their own verification" on public.bill_verifications
      for insert to authenticated with check (user_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='bill_verifications' and policyname='Users can read their own verification') then
    create policy "Users can read their own verification" on public.bill_verifications
      for select to authenticated using (user_id = auth.uid());
  end if;
  if not exists (select 1 from pg_trigger where tgname='bill_verifications_set_updated_at') then
    create trigger bill_verifications_set_updated_at before update on public.bill_verifications
      for each row execute function public.set_updated_at();
  end if;
end $$;

-- Badge signal on reviews: non-null once an admin approves a verification.
alter table public.property_reviews add column if not exists verified_at timestamptz;

grant all on public.bill_verifications to service_role;
grant select, insert on public.bill_verifications to authenticated;
