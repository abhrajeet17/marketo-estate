-- Migration: Add user_invites table for tracking admin-sent invitations
-- Run this in Supabase SQL Editor

-- 20) User Invites (track email invitations sent by admins)
create table if not exists public.user_invites (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  invited_by uuid not null references auth.users(id) on delete cascade,
  email text not null,
  display_name text not null,
  role text not null default 'user' check (role in ('admin', 'user', 'broker')),
  status text not null default 'pending' check (status in ('pending', 'accepted', 'expired')),
  invited_user_id uuid references auth.users(id) on delete set null,
  created_at timestamptz default now(),
  accepted_at timestamptz
);

create index if not exists idx_user_invites_org on public.user_invites(org_id);
create index if not exists idx_user_invites_email on public.user_invites(email);
create index if not exists idx_user_invites_invited_by on public.user_invites(invited_by);
create index if not exists idx_user_invites_status on public.user_invites(status);
