-- Properties are canonical/shared data (like a map place), not owned by whoever
-- first reviewed the location. The old "Property creators can update their
-- properties" UPDATE policy granted edit rights to that first reviewer -- exactly
-- who should NOT be able to rename a property. Property editing is now admin-only
-- (done server-side via the service role, which bypasses RLS), so there is no
-- user UPDATE policy at all. Reviews remain locked to their authors separately.

drop policy if exists "Property creators can update their properties" on public.properties;
