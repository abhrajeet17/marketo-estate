-- Migration: unify client-member broker roles.
-- Run this in Supabase SQL Editor after backing up role data if needed.

alter table public.profiles
  drop constraint if exists profiles_role_check;

update public.profiles
set role = 'broker'
where role = 'external_broker';

alter table public.profiles
  add constraint profiles_role_check
  check (role in ('superadmin', 'admin', 'user', 'broker'));

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

alter table public.client_members
  drop constraint if exists client_members_member_role_check;

update public.client_members
set member_role = 'broker'
where member_role in ('internal_broker', 'external_broker');

alter table public.client_members
  add constraint client_members_member_role_check
  check (member_role in ('client_admin', 'client_user', 'broker'));

do $$
begin
  if to_regclass('public.client_team_invites') is not null then
    alter table public.client_team_invites
      drop constraint if exists client_team_invites_member_role_check;

    update public.client_team_invites
    set member_role = 'broker'
    where member_role in ('internal_broker', 'external_broker');

    alter table public.client_team_invites
      add constraint client_team_invites_member_role_check
      check (member_role in ('client_admin', 'client_user', 'broker'));

    alter table public.client_team_invites
      drop constraint if exists client_team_invites_status_check;

    alter table public.client_team_invites
      add constraint client_team_invites_status_check
      check (status in ('pending', 'accepted', 'expired', 'cancelled', 'rejected'));
  end if;
end
$$;
