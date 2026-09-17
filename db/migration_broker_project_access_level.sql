-- Migration: add broker project access level
-- Broker access can use CRM and share customer links, but is not allowed into client/admin edit modes.

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conrelid = 'public.workspace_access'::regclass
      and conname = 'workspace_access_access_type_check'
  ) then
    alter table public.workspace_access
      drop constraint workspace_access_access_type_check;
  end if;

  alter table public.workspace_access
    add constraint workspace_access_access_type_check
    check (access_type in ('client', 'broker', 'viewer'));
end $$;

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conrelid = 'public.panorama_access'::regclass
      and conname = 'panorama_access_access_type_check'
  ) then
    alter table public.panorama_access
      drop constraint panorama_access_access_type_check;
  end if;

  alter table public.panorama_access
    add constraint panorama_access_access_type_check
    check (access_type in ('client', 'broker', 'viewer'));
end $$;
