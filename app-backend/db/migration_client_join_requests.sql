-- Self-service onboarding: a signed-up user without a client group asks to join one.
-- The group's Client Admin approves (the user becomes a member with the requested role) or declines.
create table if not exists public.client_join_requests (
  id           uuid primary key default gen_random_uuid(),
  client_id    uuid not null references public.clients(id) on delete cascade,
  org_id       uuid not null references public.organizations(id) on delete cascade,
  user_id      uuid not null references auth.users(id) on delete cascade,
  member_role  text not null default 'client_user'
               check (member_role in ('client_user', 'broker')),
  message      text not null default '',
  status       text not null default 'pending'
               check (status in ('pending', 'approved', 'rejected', 'cancelled')),
  decided_by   uuid references auth.users(id) on delete set null,
  decided_at   timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- One open request per user at a time.
create unique index if not exists uq_client_join_requests_pending_user
  on public.client_join_requests(user_id) where status = 'pending';
create index if not exists idx_client_join_requests_client_status
  on public.client_join_requests(client_id, status, created_at desc);

-- Only the backend (service role) reads or writes this table.
alter table public.client_join_requests enable row level security;
