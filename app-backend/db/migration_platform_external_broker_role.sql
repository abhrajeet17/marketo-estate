-- Migration: allow broker as a platform user role
-- Run this in Supabase SQL Editor

-- profiles.role: superadmin | admin | user | broker
alter table public.profiles
  drop constraint if exists profiles_role_check;

update public.profiles
set role = 'broker'
where role = 'external_broker';

alter table public.profiles
  add constraint profiles_role_check
  check (role in ('superadmin', 'admin', 'user', 'broker'));

-- user_invites.role: admin | user | broker
do $$
begin
  if to_regclass('public.user_invites') is not null then
    alter table public.user_invites
      drop constraint if exists user_invites_role_check;

    update public.user_invites
    set role = 'broker'
    where role = 'external_broker';

    alter table public.user_invites
      add constraint user_invites_role_check
      check (role in ('admin', 'user', 'broker'));
  end if;
end
$$;
