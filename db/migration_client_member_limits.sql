-- Add an editable member capacity to each client group.
-- Active members and non-expired pending invitations consume capacity.

alter table public.clients
  add column if not exists members_allowed integer not null default 10;

alter table public.clients
  drop constraint if exists clients_members_allowed_check;

alter table public.clients
  add constraint clients_members_allowed_check
  check (members_allowed >= 1);
