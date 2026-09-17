-- Migration: client-group scoping for CRM (interests, contacts, deals)
-- Goal:
-- 1) Add client_id to CRM tables.
-- 2) Backfill best-effort client_id for existing rows.
-- 3) Add client-scope indexes and contact uniqueness by org+client.
-- 4) Keep admin/superadmin unrestricted at API layer; non-admin filtered by client_id.

begin;

alter table if exists public.buy_interests
  add column if not exists client_id uuid references public.clients(id) on delete set null;

alter table if exists public.crm_contacts
  add column if not exists client_id uuid references public.clients(id) on delete set null;

alter table if exists public.crm_deals
  add column if not exists client_id uuid references public.clients(id) on delete set null;

-- Backfill from creator memberships first (most explicit ownership).
update public.buy_interests bi
set client_id = cm.client_id
from public.client_members cm
where bi.client_id is null
  and bi.submitted_by is not null
  and cm.user_id = bi.submitted_by;

update public.crm_contacts c
set client_id = cm.client_id
from public.client_members cm
where c.client_id is null
  and c.created_by is not null
  and cm.user_id = c.created_by;

update public.crm_deals d
set client_id = cm.client_id
from public.client_members cm
where d.client_id is null
  and d.created_by is not null
  and cm.user_id = d.created_by;

-- Backfill from source interest/contact relations.
update public.crm_contacts c
set client_id = bi.client_id
from public.buy_interests bi
where c.client_id is null
  and c.source_interest_id = bi.id
  and bi.client_id is not null;

update public.crm_deals d
set client_id = bi.client_id
from public.buy_interests bi
where d.client_id is null
  and d.interest_id = bi.id
  and bi.client_id is not null;

update public.crm_deals d
set client_id = c.client_id
from public.crm_contacts c
where d.client_id is null
  and d.contact_id = c.id
  and c.client_id is not null;

-- Backfill from panorama when that panorama maps to exactly one client group.
with pano_clients as (
  select
    pa.panorama_id,
    cm.client_id
  from public.panorama_access pa
  join public.client_members cm on cm.id = pa.client_member_id
  where pa.client_member_id is not null
    and cm.client_id is not null
  group by pa.panorama_id, cm.client_id
),
pano_unique as (
  select
    panorama_id,
    min(client_id) as client_id
  from pano_clients
  group by panorama_id
  having count(*) = 1
)
update public.buy_interests bi
set client_id = pu.client_id
from pano_unique pu
where bi.client_id is null
  and bi.panorama_id = pu.panorama_id;

with pano_clients as (
  select
    pa.panorama_id,
    cm.client_id
  from public.panorama_access pa
  join public.client_members cm on cm.id = pa.client_member_id
  where pa.client_member_id is not null
    and cm.client_id is not null
  group by pa.panorama_id, cm.client_id
),
pano_unique as (
  select
    panorama_id,
    min(client_id) as client_id
  from pano_clients
  group by panorama_id
  having count(*) = 1
)
update public.crm_contacts c
set client_id = pu.client_id
from pano_unique pu
where c.client_id is null
  and c.panorama_id = pu.panorama_id;

with pano_clients as (
  select
    pa.panorama_id,
    cm.client_id
  from public.panorama_access pa
  join public.client_members cm on cm.id = pa.client_member_id
  where pa.client_member_id is not null
    and cm.client_id is not null
  group by pa.panorama_id, cm.client_id
),
pano_unique as (
  select
    panorama_id,
    min(client_id) as client_id
  from pano_clients
  group by panorama_id
  having count(*) = 1
)
update public.crm_deals d
set client_id = pu.client_id
from pano_unique pu
where d.client_id is null
  and d.panorama_id = pu.panorama_id;

create index if not exists idx_buy_interests_client_id
  on public.buy_interests(client_id);

create index if not exists idx_crm_contacts_client
  on public.crm_contacts(client_id);

create index if not exists idx_crm_deals_client
  on public.crm_deals(client_id);

-- Replace org-only contact uniqueness with org+client uniqueness.
drop index if exists public.uq_crm_contacts_org_email_norm;
drop index if exists public.uq_crm_contacts_org_phone_norm;

create unique index if not exists uq_crm_contacts_org_client_email_norm
  on public.crm_contacts (
    coalesce(org_id, '00000000-0000-0000-0000-000000000000'::uuid),
    coalesce(client_id, '00000000-0000-0000-0000-000000000000'::uuid),
    email_norm
  )
  where email_norm <> '';

create unique index if not exists uq_crm_contacts_org_client_phone_norm
  on public.crm_contacts (
    coalesce(org_id, '00000000-0000-0000-0000-000000000000'::uuid),
    coalesce(client_id, '00000000-0000-0000-0000-000000000000'::uuid),
    phone_norm
  )
  where phone_norm <> '';

commit;
