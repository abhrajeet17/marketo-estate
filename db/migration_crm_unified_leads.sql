-- ============================================================================
-- Migration: Unified CRM leads table (single source of truth)
--
-- Goal
--   Interests, deals and contacts used to live in three tables
--   (buy_interests, crm_deals, crm_contacts). This migration creates ONE table,
--   public.crm_leads, where every record is either an `interest` or a `deal`
--   (record_status). The Contacts view in the CRM is simply "all deals".
--
-- Data preservation
--   * Every buy_interests row becomes a crm_leads row with the SAME id.
--   * A deal linked to an interest is merged into that interest row (the row
--     flips to record_status = 'deal', deal_* columns are filled).
--     If several deals point at one interest, the active/most recent one is
--     merged and the others become their own deal rows (id = old deal id).
--   * Deals with no interest become deal rows (id = old deal id) with the
--     customer fields copied from their crm_contacts row.
--   * Contacts linked to an interest/deal enrich that row (birthday, address,
--     notes, custom fields). Contacts linked to nothing become deal rows
--     (id = old contact id, stage 'new') so no contact is lost.
--   * crm_deal_quotes.deal_id is re-pointed at crm_leads (quotes survive).
--   * reference_user_role is back-filled from client_members.
--   * The legacy tables are NOT dropped. They stay as read-only history; a
--     commented cleanup block is at the end of this file.
--
-- Safe to re-run: every step is guarded (if not exists / on conflict /
-- "legacy_* is null" predicates).
--
-- Run AFTER all previous CRM migrations (schema.sql state).
-- ============================================================================

begin;

-- ---------------------------------------------------------------------------
-- 1) Table
-- ---------------------------------------------------------------------------
create table if not exists public.crm_leads (
  id uuid primary key default gen_random_uuid(),
  record_status text not null default 'interest'
    check (record_status in ('interest', 'deal')),

  -- scope
  org_id uuid references public.organizations(id) on delete set null,
  client_id uuid references public.clients(id) on delete set null,
  panorama_id bigint not null references public.panoramas(id) on delete cascade,

  -- ownership / reference
  submitted_by uuid references auth.users(id) on delete set null,
  reference_user_id uuid references auth.users(id) on delete set null,
  reference_user_role text
    check (reference_user_role is null or reference_user_role in ('broker', 'client_admin', 'client_user')),
  contact_revealed_at timestamptz,
  assigned_to uuid references auth.users(id) on delete set null,
  assigned_at timestamptz,

  -- customer / contact
  customer_name text not null default '',
  customer_email text not null default '',
  customer_phone text not null default '',
  customer_birthday date,
  customer_address text,
  customer_street text,
  customer_city text,
  customer_state text,
  customer_country text,
  customer_zip_code text,
  email_norm text generated always as (lower(btrim(customer_email))) stored,
  phone_norm text generated always as (regexp_replace(customer_phone, '[^0-9]+', '', 'g')) stored,

  -- lead classification
  title text,
  description text,
  category text not null default '',
  lead_source text,
  lead_category text,
  lead_status text,
  campaign_type text,
  campaign_status text,
  plots jsonb not null default '[]'::jsonb,
  notes text not null default '',
  custom_fields jsonb not null default '{}'::jsonb,

  -- deal (only meaningful when record_status = 'deal')
  deal_title text not null default '',
  deal_stage text not null default 'new'
    check (deal_stage in ('new', 'contacted', 'site_visit', 'negotiation', 'won', 'lost')),
  deal_amount text not null default '',
  deal_currency text not null default 'INR',
  deal_is_active boolean not null default true,
  deal_project_name text not null default '',
  converted_at timestamptz,
  converted_by uuid references auth.users(id) on delete set null,

  -- traceability back to the legacy tables
  legacy_interest_id uuid,
  legacy_deal_id uuid,
  legacy_contact_id uuid,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_crm_leads_panorama_created
  on public.crm_leads(panorama_id, created_at desc);
create index if not exists idx_crm_leads_status_panorama_created
  on public.crm_leads(record_status, panorama_id, created_at desc);
create index if not exists idx_crm_leads_client_created
  on public.crm_leads(client_id, created_at desc);
create index if not exists idx_crm_leads_reference_user
  on public.crm_leads(reference_user_id);
create index if not exists idx_crm_leads_submitted_by
  on public.crm_leads(submitted_by);
create index if not exists idx_crm_leads_assigned_to
  on public.crm_leads(assigned_to);
create index if not exists idx_crm_leads_email_norm
  on public.crm_leads(email_norm) where email_norm <> '';
create index if not exists idx_crm_leads_phone_norm
  on public.crm_leads(phone_norm) where phone_norm <> '';
create index if not exists idx_crm_leads_deal_stage
  on public.crm_leads(deal_stage) where record_status = 'deal';
create index if not exists idx_crm_leads_updated
  on public.crm_leads(updated_at desc);
create index if not exists idx_crm_leads_legacy_deal
  on public.crm_leads(legacy_deal_id) where legacy_deal_id is not null;
create index if not exists idx_crm_leads_legacy_contact
  on public.crm_leads(legacy_contact_id) where legacy_contact_id is not null;
create index if not exists idx_crm_leads_plots_gin
  on public.crm_leads using gin (plots jsonb_path_ops);

-- ---------------------------------------------------------------------------
-- 2) Interests -> leads (same id)
-- ---------------------------------------------------------------------------
insert into public.crm_leads (
  id, record_status, org_id, client_id, panorama_id,
  submitted_by, reference_user_id, contact_revealed_at, assigned_to, assigned_at,
  customer_name, customer_email, customer_phone, customer_birthday, customer_address,
  customer_street, customer_city, customer_state, customer_country, customer_zip_code,
  title, description, category,
  lead_source, lead_category, lead_status, campaign_type, campaign_status,
  plots, notes, custom_fields,
  legacy_interest_id, created_at, updated_at
)
select
  bi.id, 'interest', p.org_id, bi.client_id, bi.panorama_id,
  bi.submitted_by, bi.reference_user_id, bi.contact_revealed_at, bi.assigned_to, bi.assigned_at,
  coalesce(bi.customer_name, ''), coalesce(bi.customer_email, ''), coalesce(bi.customer_phone, ''),
  bi.customer_birthday, nullif(bi.customer_address, ''),
  nullif(bi.customer_street, ''), nullif(bi.customer_city, ''), nullif(bi.customer_state, ''),
  nullif(bi.customer_country, ''), nullif(bi.customer_zip_code, ''),
  nullif(bi.title, ''), nullif(bi.description, ''), coalesce(bi.category, ''),
  nullif(bi.lead_source, ''), nullif(bi.lead_category, ''), nullif(bi.lead_status, ''),
  nullif(bi.campaign_type, ''), nullif(bi.campaign_status, ''),
  case when jsonb_typeof(coalesce(bi.plots, '[]'::jsonb)) = 'array' then coalesce(bi.plots, '[]'::jsonb) else '[]'::jsonb end,
  coalesce(bi.notes, ''),
  case when jsonb_typeof(coalesce(bi.custom_fields, '{}'::jsonb)) = 'object' then coalesce(bi.custom_fields, '{}'::jsonb) else '{}'::jsonb end,
  bi.id, coalesce(bi.created_at, now()), coalesce(bi.updated_at, bi.created_at, now())
from public.buy_interests bi
join public.panoramas p on p.id = bi.panorama_id
on conflict (id) do nothing;

-- Enrich interests from the contact they were linked to (birthday, address,
-- notes, custom fields) so nothing typed on the old Contacts tab is lost.
update public.crm_leads l
set
  customer_birthday = coalesce(l.customer_birthday, c.birthday),
  customer_address  = coalesce(nullif(l.customer_address, ''), nullif(c.address, '')),
  notes             = case when coalesce(l.notes, '') = '' then coalesce(c.notes, '') else l.notes end,
  custom_fields     = coalesce(c.custom_fields, '{}'::jsonb) || coalesce(l.custom_fields, '{}'::jsonb),
  legacy_contact_id = coalesce(l.legacy_contact_id, c.id)
from public.buy_interests bi
join public.crm_contacts c on c.id = bi.contact_id
where l.id = bi.id
  and l.legacy_contact_id is null;

-- Contacts that point back at an interest via source_interest_id but were
-- never linked from the interest side.
update public.crm_leads l
set
  customer_birthday = coalesce(l.customer_birthday, c.birthday),
  customer_address  = coalesce(nullif(l.customer_address, ''), nullif(c.address, '')),
  notes             = case when coalesce(l.notes, '') = '' then coalesce(c.notes, '') else l.notes end,
  custom_fields     = coalesce(c.custom_fields, '{}'::jsonb) || coalesce(l.custom_fields, '{}'::jsonb),
  legacy_contact_id = c.id
from public.crm_contacts c
where c.source_interest_id = l.id
  and l.legacy_contact_id is null;

-- ---------------------------------------------------------------------------
-- 3) Deals
-- ---------------------------------------------------------------------------
-- Rank deals per interest: the active one first, then the most recent.
drop table if exists tmp_crm_deal_rank;
create temporary table tmp_crm_deal_rank on commit drop as
select
  d.*,
  row_number() over (
    partition by d.interest_id
    order by d.is_active desc, d.updated_at desc nulls last, d.created_at desc nulls last
  ) as rn
from public.crm_deals d
where d.interest_id is not null;

-- 3a) Primary deal merges INTO its interest row (row becomes a deal).
update public.crm_leads l
set
  record_status     = 'deal',
  deal_title        = coalesce(nullif(r.title, ''), l.customer_name, ''),
  deal_stage        = case when r.stage in ('new','contacted','site_visit','negotiation','won','lost') then r.stage else 'new' end,
  deal_amount       = coalesce(r.amount, ''),
  deal_currency     = coalesce(nullif(r.currency, ''), 'INR'),
  deal_is_active    = coalesce(r.is_active, true),
  deal_project_name = coalesce(r.project_name, ''),
  plots             = case
                        when jsonb_typeof(coalesce(r.plots, '[]'::jsonb)) = 'array' and jsonb_array_length(coalesce(r.plots, '[]'::jsonb)) > 0
                          then r.plots
                        else l.plots
                      end,
  notes             = case
                        when coalesce(l.notes, '') = '' then coalesce(r.notes, '')
                        when coalesce(r.notes, '') = '' or r.notes = l.notes then l.notes
                        else l.notes || E'\n\n' || r.notes
                      end,
  custom_fields     = coalesce(l.custom_fields, '{}'::jsonb) || coalesce(r.custom_fields, '{}'::jsonb),
  client_id         = coalesce(l.client_id, r.client_id),
  org_id            = coalesce(l.org_id, r.org_id),
  legacy_deal_id    = r.id,
  legacy_contact_id = coalesce(l.legacy_contact_id, r.contact_id),
  converted_at      = coalesce(r.created_at, l.created_at, now()),
  converted_by      = r.created_by,
  updated_at        = greatest(coalesce(l.updated_at, l.created_at, now()), coalesce(r.updated_at, r.created_at, l.created_at, now()))
from tmp_crm_deal_rank r
where r.rn = 1
  and l.id = r.interest_id
  and l.legacy_deal_id is null;

-- 3b) Additional deals on the same interest become their own deal rows,
--     copying the customer from the interest.
insert into public.crm_leads (
  id, record_status, org_id, client_id, panorama_id,
  submitted_by, reference_user_id, reference_user_role, contact_revealed_at, assigned_to, assigned_at,
  customer_name, customer_email, customer_phone, customer_birthday, customer_address,
  customer_street, customer_city, customer_state, customer_country, customer_zip_code,
  title, description, category,
  lead_source, lead_category, lead_status, campaign_type, campaign_status,
  plots, notes, custom_fields,
  deal_title, deal_stage, deal_amount, deal_currency, deal_is_active, deal_project_name,
  converted_at, converted_by,
  legacy_interest_id, legacy_deal_id, legacy_contact_id,
  created_at, updated_at
)
select
  r.id, 'deal', coalesce(r.org_id, l.org_id), coalesce(r.client_id, l.client_id), r.panorama_id,
  coalesce(r.created_by, l.submitted_by), l.reference_user_id, l.reference_user_role, l.contact_revealed_at, l.assigned_to, l.assigned_at,
  l.customer_name, l.customer_email, l.customer_phone, l.customer_birthday, l.customer_address,
  l.customer_street, l.customer_city, l.customer_state, l.customer_country, l.customer_zip_code,
  l.title, l.description, l.category,
  l.lead_source, l.lead_category, l.lead_status, l.campaign_type, l.campaign_status,
  case when jsonb_typeof(coalesce(r.plots, '[]'::jsonb)) = 'array' and jsonb_array_length(coalesce(r.plots, '[]'::jsonb)) > 0 then r.plots else l.plots end,
  coalesce(nullif(r.notes, ''), l.notes, ''),
  coalesce(l.custom_fields, '{}'::jsonb) || coalesce(r.custom_fields, '{}'::jsonb),
  coalesce(nullif(r.title, ''), l.customer_name, ''),
  case when r.stage in ('new','contacted','site_visit','negotiation','won','lost') then r.stage else 'new' end,
  coalesce(r.amount, ''), coalesce(nullif(r.currency, ''), 'INR'), coalesce(r.is_active, true), coalesce(r.project_name, ''),
  coalesce(r.created_at, now()), r.created_by,
  l.id, r.id, coalesce(r.contact_id, l.legacy_contact_id),
  coalesce(r.created_at, now()), coalesce(r.updated_at, r.created_at, now())
from tmp_crm_deal_rank r
join public.crm_leads l on l.id = r.interest_id
where r.rn > 1
on conflict (id) do nothing;

-- 3c) Deals created directly from a contact (no interest) become deal rows.
insert into public.crm_leads (
  id, record_status, org_id, client_id, panorama_id,
  submitted_by,
  customer_name, customer_email, customer_phone, customer_birthday, customer_address,
  category, plots, notes, custom_fields,
  deal_title, deal_stage, deal_amount, deal_currency, deal_is_active, deal_project_name,
  converted_at, converted_by,
  legacy_deal_id, legacy_contact_id,
  created_at, updated_at
)
select
  d.id, 'deal', coalesce(d.org_id, p.org_id), coalesce(d.client_id, c.client_id), d.panorama_id,
  d.created_by,
  coalesce(nullif(c.full_name, ''), nullif(d.title, ''), ''), coalesce(c.email, ''), coalesce(c.phone, ''),
  c.birthday, nullif(c.address, ''),
  '',
  case when jsonb_typeof(coalesce(d.plots, '[]'::jsonb)) = 'array' then coalesce(d.plots, '[]'::jsonb) else '[]'::jsonb end,
  case
    when coalesce(c.notes, '') = '' then coalesce(d.notes, '')
    when coalesce(d.notes, '') = '' or d.notes = c.notes then c.notes
    else c.notes || E'\n\n' || d.notes
  end,
  coalesce(c.custom_fields, '{}'::jsonb) || coalesce(d.custom_fields, '{}'::jsonb),
  coalesce(nullif(d.title, ''), nullif(c.full_name, ''), ''),
  case when d.stage in ('new','contacted','site_visit','negotiation','won','lost') then d.stage else 'new' end,
  coalesce(d.amount, ''), coalesce(nullif(d.currency, ''), 'INR'), coalesce(d.is_active, true),
  coalesce(nullif(d.project_name, ''), p.name, ''),
  coalesce(d.created_at, now()), d.created_by,
  d.id, c.id,
  coalesce(d.created_at, now()), coalesce(d.updated_at, d.created_at, now())
from public.crm_deals d
join public.panoramas p on p.id = d.panorama_id
left join public.crm_contacts c on c.id = d.contact_id
where d.interest_id is null
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- 4) Contacts that are linked to nothing become deal rows (stage 'new') so
--    they still show on the Contacts tab (= all deals).
-- ---------------------------------------------------------------------------
insert into public.crm_leads (
  id, record_status, org_id, client_id, panorama_id,
  submitted_by,
  customer_name, customer_email, customer_phone, customer_birthday, customer_address,
  category, plots, notes, custom_fields,
  deal_title, deal_stage, deal_amount, deal_currency, deal_is_active, deal_project_name,
  converted_at, converted_by,
  legacy_contact_id,
  created_at, updated_at
)
select
  c.id, 'deal', coalesce(c.org_id, p.org_id), c.client_id, c.panorama_id,
  c.created_by,
  coalesce(c.full_name, ''), coalesce(c.email, ''), coalesce(c.phone, ''), c.birthday, nullif(c.address, ''),
  '', '[]'::jsonb, coalesce(c.notes, ''),
  coalesce(c.custom_fields, '{}'::jsonb) || jsonb_build_object('migrated_from', 'crm_contacts'),
  coalesce(nullif(c.full_name, ''), 'Contact'), 'new', '', 'INR', true, coalesce(p.name, ''),
  coalesce(c.created_at, now()), c.created_by,
  c.id,
  coalesce(c.created_at, now()), coalesce(c.updated_at, c.created_at, now())
from public.crm_contacts c
join public.panoramas p on p.id = c.panorama_id
where not exists (select 1 from public.crm_leads l where l.legacy_contact_id = c.id or l.id = c.id)
  and not exists (select 1 from public.buy_interests bi where bi.contact_id = c.id)
  and not exists (select 1 from public.crm_deals d where d.contact_id = c.id)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- 5) Back-fills
-- ---------------------------------------------------------------------------
-- org_id from the panorama when still missing
update public.crm_leads l
set org_id = p.org_id
from public.panoramas p
where l.org_id is null and p.id = l.panorama_id and p.org_id is not null;

-- reference_user_role from client_members (prefer the membership in the
-- lead's own client group; otherwise broker > client_admin > client_user)
update public.crm_leads l
set reference_user_role = sub.member_role
from (
  select
    l2.id as lead_id,
    (
      select case when cm.member_role = 'sales_agent' then 'client_user' else cm.member_role end
      from public.client_members cm
      where cm.user_id = l2.reference_user_id
        and cm.member_role in ('broker', 'client_admin', 'client_user', 'sales_agent')
      order by
        (cm.client_id = l2.client_id) desc nulls last,
        case cm.member_role when 'broker' then 0 when 'client_admin' then 1 else 2 end
      limit 1
    ) as member_role
  from public.crm_leads l2
  where l2.reference_user_id is not null
    and l2.reference_user_role is null
) sub
where l.id = sub.lead_id
  and sub.member_role is not null;

-- ---------------------------------------------------------------------------
-- 6) Quotes now hang off crm_leads
-- ---------------------------------------------------------------------------
alter table public.crm_deal_quotes drop constraint if exists crm_deal_quotes_deal_id_fkey;
alter table public.crm_deal_quotes drop constraint if exists crm_deal_quotes_contact_id_fkey;

-- primary deals were merged into their interest row -> follow the id
update public.crm_deal_quotes q
set deal_id = r.interest_id
from tmp_crm_deal_rank r
where r.rn = 1
  and q.deal_id = r.id
  and r.interest_id is not null;

-- the lead IS the contact now
update public.crm_deal_quotes q
set contact_id = q.deal_id
where exists (select 1 from public.crm_leads l where l.id = q.deal_id);

-- (defensive) quotes whose deal no longer exists anywhere cannot satisfy the FK
delete from public.crm_deal_quotes q
where not exists (select 1 from public.crm_leads l where l.id = q.deal_id);

alter table public.crm_deal_quotes
  add constraint crm_deal_quotes_deal_id_fkey
  foreign key (deal_id) references public.crm_leads(id) on delete cascade;
alter table public.crm_deal_quotes
  add constraint crm_deal_quotes_contact_id_fkey
  foreign key (contact_id) references public.crm_leads(id) on delete set null;

commit;

-- ---------------------------------------------------------------------------
-- Verification (run manually; not part of the migration)
-- ---------------------------------------------------------------------------
-- select record_status, count(*) from public.crm_leads group by 1;
-- select count(*) as interests_src from public.buy_interests;
-- select count(*) as deals_src from public.crm_deals;
-- select count(*) as contacts_src from public.crm_contacts;
-- select count(*) as leads_without_org from public.crm_leads where org_id is null;

-- ---------------------------------------------------------------------------
-- OPTIONAL cleanup — only after the new CRM has been verified in production.
-- The application no longer reads or writes these tables.
-- ---------------------------------------------------------------------------
-- alter table public.buy_interests rename to buy_interests_legacy;
-- alter table public.crm_contacts  rename to crm_contacts_legacy;
-- alter table public.crm_deals     rename to crm_deals_legacy;
