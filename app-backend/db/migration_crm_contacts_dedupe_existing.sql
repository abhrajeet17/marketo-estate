-- Migration: dedupe existing CRM contacts by same email OR same phone (within org),
-- normalize case/spacing, and enforce uniqueness moving forward.
-- Run once in Supabase SQL Editor.

begin;

alter table if exists public.crm_contacts
  add column if not exists client_id uuid references public.clients(id) on delete set null;

-- 1) Normalize current data
update public.crm_contacts
set
  email = btrim(coalesce(email, '')),
  phone = btrim(coalesce(phone, '')),
  full_name = regexp_replace(btrim(coalesce(full_name, '')), '\s+', ' ', 'g'),
  email_norm = lower(btrim(coalesce(email, ''))),
  phone_norm = regexp_replace(coalesce(phone, ''), '[^0-9]+', '', 'g'),
  updated_at = now();

-- 2) Build duplicate groups (connected components by shared email_norm or phone_norm)
with recursive
base as (
  select
    id,
    coalesce(org_id::text, '__NOORG__') as org_key,
    nullif(lower(btrim(coalesce(email_norm, ''))), '') as email_key,
    nullif(regexp_replace(coalesce(phone_norm, ''), '[^0-9]+', '', 'g'), '') as phone_key,
    created_at
  from public.crm_contacts
),
edges as (
  select a.id as from_id, b.id as to_id
  from base a
  join base b
    on a.org_key = b.org_key
   and a.id <> b.id
   and (
     (a.email_key is not null and a.email_key = b.email_key)
     or
     (a.phone_key is not null and a.phone_key = b.phone_key)
   )
),
walk as (
  select id as start_id, id as node_id
  from base
  union
  select w.start_id, e.to_id
  from walk w
  join edges e on e.from_id = w.node_id
),
components as (
  select node_id as id, min(start_id::text)::uuid as component_id
  from walk
  group by node_id
),
ranked as (
  select
    c.id,
    c.component_id,
    cc.created_at,
    row_number() over (
      partition by c.component_id
      order by cc.created_at asc nulls last, cc.id asc
    ) as rn
  from components c
  join public.crm_contacts cc on cc.id = c.id
),
keepers as (
  select id as keeper_id, component_id
  from ranked
  where rn = 1
),
dups as (
  select r.id as dup_id, k.keeper_id
  from ranked r
  join keepers k on k.component_id = r.component_id
  where r.rn > 1
),
best_data as (
  select
    k.keeper_id,
    (array_agg(nullif(regexp_replace(btrim(coalesce(c.full_name, '')), '\s+', ' ', 'g'), '') order by length(nullif(regexp_replace(btrim(coalesce(c.full_name, '')), '\s+', ' ', 'g'), '')) desc nulls last))[1] as best_name,
    (array_agg(nullif(c.email, '') order by (nullif(c.email_norm, '') is not null) desc, c.updated_at desc nulls last))[1] as best_email,
    (array_agg(nullif(c.phone, '') order by (nullif(c.phone_norm, '') is not null) desc, c.updated_at desc nulls last))[1] as best_phone,
    (array_agg(nullif(c.notes, '') order by length(coalesce(c.notes, '')) desc nulls last))[1] as best_notes
  from keepers k
  join components comp on comp.component_id = k.component_id
  join public.crm_contacts c on c.id = comp.id
  group by k.keeper_id
)
-- 3) Re-point references from duplicate contacts -> keeper
update public.buy_interests bi
set
  contact_id = d.keeper_id,
  updated_at = now()
from dups d
where bi.contact_id = d.dup_id;

with recursive
base as (
  select
    id,
    coalesce(org_id::text, '__NOORG__') as org_key,
    nullif(lower(btrim(coalesce(email_norm, ''))), '') as email_key,
    nullif(regexp_replace(coalesce(phone_norm, ''), '[^0-9]+', '', 'g'), '') as phone_key
  from public.crm_contacts
),
edges as (
  select a.id as from_id, b.id as to_id
  from base a
  join base b
    on a.org_key = b.org_key
   and a.id <> b.id
   and (
     (a.email_key is not null and a.email_key = b.email_key)
     or
     (a.phone_key is not null and a.phone_key = b.phone_key)
   )
),
walk as (
  select id as start_id, id as node_id
  from base
  union
  select w.start_id, e.to_id
  from walk w
  join edges e on e.from_id = w.node_id
),
components as (
  select node_id as id, min(start_id::text)::uuid as component_id
  from walk
  group by node_id
),
ranked as (
  select
    c.id,
    c.component_id,
    cc.created_at,
    row_number() over (
      partition by c.component_id
      order by cc.created_at asc nulls last, cc.id asc
    ) as rn
  from components c
  join public.crm_contacts cc on cc.id = c.id
),
keepers as (
  select id as keeper_id, component_id
  from ranked
  where rn = 1
),
dups as (
  select r.id as dup_id, k.keeper_id
  from ranked r
  join keepers k on k.component_id = r.component_id
  where r.rn > 1
)
update public.crm_deals d0
set contact_id = d.keeper_id
from dups d
where d0.contact_id = d.dup_id;

with recursive
base as (
  select
    id,
    coalesce(org_id::text, '__NOORG__') as org_key,
    nullif(lower(btrim(coalesce(email_norm, ''))), '') as email_key,
    nullif(regexp_replace(coalesce(phone_norm, ''), '[^0-9]+', '', 'g'), '') as phone_key
  from public.crm_contacts
),
edges as (
  select a.id as from_id, b.id as to_id
  from base a
  join base b
    on a.org_key = b.org_key
   and a.id <> b.id
   and (
     (a.email_key is not null and a.email_key = b.email_key)
     or
     (a.phone_key is not null and a.phone_key = b.phone_key)
   )
),
walk as (
  select id as start_id, id as node_id
  from base
  union
  select w.start_id, e.to_id
  from walk w
  join edges e on e.from_id = w.node_id
),
components as (
  select node_id as id, min(start_id::text)::uuid as component_id
  from walk
  group by node_id
),
ranked as (
  select
    c.id,
    c.component_id,
    cc.created_at,
    row_number() over (
      partition by c.component_id
      order by cc.created_at asc nulls last, cc.id asc
    ) as rn
  from components c
  join public.crm_contacts cc on cc.id = c.id
),
keepers as (
  select id as keeper_id, component_id
  from ranked
  where rn = 1
),
dups as (
  select r.id as dup_id, k.keeper_id
  from ranked r
  join keepers k on k.component_id = r.component_id
  where r.rn > 1
)
update public.crm_deal_quotes q
set contact_id = d.keeper_id
from dups d
where q.contact_id = d.dup_id;

-- 4) Update keeper rows with best available values in each group
with recursive
base as (
  select
    id,
    coalesce(org_id::text, '__NOORG__') as org_key,
    nullif(lower(btrim(coalesce(email_norm, ''))), '') as email_key,
    nullif(regexp_replace(coalesce(phone_norm, ''), '[^0-9]+', '', 'g'), '') as phone_key,
    created_at
  from public.crm_contacts
),
edges as (
  select a.id as from_id, b.id as to_id
  from base a
  join base b
    on a.org_key = b.org_key
   and a.id <> b.id
   and (
     (a.email_key is not null and a.email_key = b.email_key)
     or
     (a.phone_key is not null and a.phone_key = b.phone_key)
   )
),
walk as (
  select id as start_id, id as node_id
  from base
  union
  select w.start_id, e.to_id
  from walk w
  join edges e on e.from_id = w.node_id
),
components as (
  select node_id as id, min(start_id::text)::uuid as component_id
  from walk
  group by node_id
),
ranked as (
  select
    c.id,
    c.component_id,
    cc.created_at,
    row_number() over (
      partition by c.component_id
      order by cc.created_at asc nulls last, cc.id asc
    ) as rn
  from components c
  join public.crm_contacts cc on cc.id = c.id
),
keepers as (
  select id as keeper_id, component_id
  from ranked
  where rn = 1
),
best_data as (
  select
    k.keeper_id,
    (array_agg(nullif(regexp_replace(btrim(coalesce(c.full_name, '')), '\s+', ' ', 'g'), '') order by length(nullif(regexp_replace(btrim(coalesce(c.full_name, '')), '\s+', ' ', 'g'), '')) desc nulls last))[1] as best_name,
    (array_agg(nullif(c.email, '') order by (nullif(c.email_norm, '') is not null) desc, c.updated_at desc nulls last))[1] as best_email,
    (array_agg(nullif(c.phone, '') order by (nullif(c.phone_norm, '') is not null) desc, c.updated_at desc nulls last))[1] as best_phone,
    (array_agg(nullif(c.notes, '') order by length(coalesce(c.notes, '')) desc nulls last))[1] as best_notes
  from keepers k
  join components comp on comp.component_id = k.component_id
  join public.crm_contacts c on c.id = comp.id
  group by k.keeper_id
)
update public.crm_contacts c
set
  full_name = coalesce(best_data.best_name, c.full_name),
  email = coalesce(best_data.best_email, c.email),
  phone = coalesce(best_data.best_phone, c.phone),
  notes = coalesce(best_data.best_notes, c.notes),
  email_norm = lower(btrim(coalesce(coalesce(best_data.best_email, c.email), ''))),
  phone_norm = regexp_replace(coalesce(coalesce(best_data.best_phone, c.phone), ''), '[^0-9]+', '', 'g'),
  updated_at = now()
from best_data
where c.id = best_data.keeper_id;

-- 5) Delete duplicate rows
with recursive
base as (
  select
    id,
    coalesce(org_id::text, '__NOORG__') as org_key,
    nullif(lower(btrim(coalesce(email_norm, ''))), '') as email_key,
    nullif(regexp_replace(coalesce(phone_norm, ''), '[^0-9]+', '', 'g'), '') as phone_key,
    created_at
  from public.crm_contacts
),
edges as (
  select a.id as from_id, b.id as to_id
  from base a
  join base b
    on a.org_key = b.org_key
   and a.id <> b.id
   and (
     (a.email_key is not null and a.email_key = b.email_key)
     or
     (a.phone_key is not null and a.phone_key = b.phone_key)
   )
),
walk as (
  select id as start_id, id as node_id
  from base
  union
  select w.start_id, e.to_id
  from walk w
  join edges e on e.from_id = w.node_id
),
components as (
  select node_id as id, min(start_id::text)::uuid as component_id
  from walk
  group by node_id
),
ranked as (
  select
    c.id,
    c.component_id,
    cc.created_at,
    row_number() over (
      partition by c.component_id
      order by cc.created_at asc nulls last, cc.id asc
    ) as rn
  from components c
  join public.crm_contacts cc on cc.id = c.id
)
delete from public.crm_contacts c
using ranked r
where c.id = r.id
  and r.rn > 1;

-- 6) Prevent duplicates going forward (per org + client group)
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
