-- Migration: Client team invites (email + share-link acceptance flow)

create table if not exists public.client_team_invites (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references public.clients(id) on delete cascade,
  org_id            uuid not null references public.organizations(id) on delete cascade,
  invited_by        uuid references auth.users(id) on delete set null,
  email             text not null,
  display_name      text not null default '',
  member_role       text not null default 'client_user'
                    check (member_role in ('client_admin', 'client_user', 'broker')),
  invite_token      text not null unique,
  invite_link       text,
  status            text not null default 'pending'
                    check (status in ('pending', 'accepted', 'expired', 'cancelled', 'rejected')),
  expires_at        timestamptz,
  accepted_at       timestamptz,
  accepted_user_id  uuid references auth.users(id) on delete set null,
  created_at        timestamptz default now(),
  updated_at        timestamptz default now()
);

create index if not exists idx_client_team_invites_client_id on public.client_team_invites(client_id);
create index if not exists idx_client_team_invites_org_id on public.client_team_invites(org_id);
create index if not exists idx_client_team_invites_email on public.client_team_invites(email);
create index if not exists idx_client_team_invites_status on public.client_team_invites(status);
create index if not exists idx_client_team_invites_token on public.client_team_invites(invite_token);
