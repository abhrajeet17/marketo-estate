-- Migration: add broker/customer reference support for buy interests
-- Run this in Supabase SQL Editor

alter table public.buy_interests
  add column if not exists reference_user_id uuid references auth.users(id) on delete set null;

create index if not exists idx_buy_interests_reference_user_id
  on public.buy_interests(reference_user_id);

alter table public.client_members
  drop constraint if exists client_members_member_role_check;

alter table public.client_members
  add constraint client_members_member_role_check
  check (member_role in ('client_admin', 'client_user', 'broker'));

alter table public.client_team_invites
  drop constraint if exists client_team_invites_member_role_check;

alter table public.client_team_invites
  add constraint client_team_invites_member_role_check
  check (member_role in ('client_admin', 'client_user', 'broker'));
