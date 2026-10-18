-- Migration: CRM contacts + deals + deal-wise quotations

-- 1) Interests: simplify to intake-contacted state + contact linkage
alter table if exists public.buy_interests
  add column if not exists is_contacted boolean not null default false;

alter table if exists public.buy_interests
  add column if not exists contacted_at timestamptz;

alter table if exists public.buy_interests
  add column if not exists contact_id uuid;

alter table if exists public.buy_interests
  add column if not exists client_id uuid references public.clients(id) on delete set null;

-- 2) CRM Contacts
create table if not exists public.crm_contacts (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references public.organizations(id) on delete set null,
  panorama_id bigint not null references public.panoramas(id) on delete cascade,
  full_name text not null default '',
  email text not null default '',
  phone text not null default '',
  email_norm text not null default '',
  phone_norm text not null default '',
  source_interest_id uuid references public.buy_interests(id) on delete set null,
  created_by uuid references auth.users(id) on delete set null,
  notes text not null default '',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_crm_contacts_org on public.crm_contacts(org_id);
alter table if exists public.crm_contacts
  add column if not exists client_id uuid references public.clients(id) on delete set null;
create index if not exists idx_crm_contacts_client on public.crm_contacts(client_id);
create index if not exists idx_crm_contacts_panorama on public.crm_contacts(panorama_id);
create index if not exists idx_crm_contacts_email_norm on public.crm_contacts(email_norm);
create index if not exists idx_crm_contacts_phone_norm on public.crm_contacts(phone_norm);
create index if not exists idx_crm_contacts_updated on public.crm_contacts(updated_at desc);

-- 3) CRM Deals (pipeline cards)
create table if not exists public.crm_deals (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references public.organizations(id) on delete set null,
  panorama_id bigint not null references public.panoramas(id) on delete cascade,
  interest_id uuid references public.buy_interests(id) on delete set null,
  contact_id uuid references public.crm_contacts(id) on delete set null,
  title text not null default '',
  stage text not null default 'new'
    check (stage in ('new', 'contacted', 'site_visit', 'negotiation', 'won', 'lost')),
  is_active boolean not null default true,
  amount text not null default '',
  currency text not null default 'INR',
  plots jsonb not null default '[]',
  project_name text not null default '',
  notes text not null default '',
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_crm_deals_org on public.crm_deals(org_id);
alter table if exists public.crm_deals
  add column if not exists client_id uuid references public.clients(id) on delete set null;
create index if not exists idx_crm_deals_client on public.crm_deals(client_id);
create index if not exists idx_crm_deals_panorama on public.crm_deals(panorama_id);
create index if not exists idx_crm_deals_contact on public.crm_deals(contact_id);
create index if not exists idx_crm_deals_interest on public.crm_deals(interest_id);
create index if not exists idx_crm_deals_stage on public.crm_deals(stage);
create index if not exists idx_crm_deals_updated on public.crm_deals(updated_at desc);

-- One active deal per interest
create unique index if not exists uq_crm_deals_interest_active
  on public.crm_deals(interest_id)
  where interest_id is not null and is_active = true;

-- 4) Deal quotations
create table if not exists public.crm_deal_quotes (
  id uuid primary key default gen_random_uuid(),
  deal_id uuid not null references public.crm_deals(id) on delete cascade,
  contact_id uuid references public.crm_contacts(id) on delete set null,
  quote_payload jsonb not null default '{}',
  share_token text not null unique,
  sent_to_email text not null default '',
  sent_to_phone text not null default '',
  shared_via text not null default ''
    check (shared_via in ('', 'email', 'link')),
  sent_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_crm_deal_quotes_deal on public.crm_deal_quotes(deal_id);
create index if not exists idx_crm_deal_quotes_contact on public.crm_deal_quotes(contact_id);
create index if not exists idx_crm_deal_quotes_created on public.crm_deal_quotes(created_at desc);
create index if not exists idx_buy_interests_contact_id on public.buy_interests(contact_id);
create index if not exists idx_buy_interests_client_id on public.buy_interests(client_id);

do $$
begin
  if not exists (
    select 1
    from information_schema.table_constraints
    where table_schema = 'public'
      and table_name = 'buy_interests'
      and constraint_name = 'buy_interests_contact_id_fkey'
  ) then
    alter table public.buy_interests
      add constraint buy_interests_contact_id_fkey
      foreign key (contact_id) references public.crm_contacts(id) on delete set null;
  end if;
end $$;

-- 5) Backfill contacted marker from legacy statuses
update public.buy_interests
set
  is_contacted = true,
  contacted_at = coalesce(contacted_at, updated_at, created_at)
where coalesce(is_contacted, false) = false
  and lower(coalesce(status, 'new')) in ('contacted', 'qualified', 'won', 'lost');

-- 6) Legacy migration: convert qualified/won/lost interests into deals + contacts
do $$
declare
  rec record;
  v_org_id uuid;
  v_contact_id uuid;
  v_stage text;
  v_now timestamptz := now();
  v_email_norm text;
  v_phone_norm text;
begin
  for rec in
    select bi.*, p.org_id, p.name as panorama_name
    from public.buy_interests bi
    join public.panoramas p on p.id = bi.panorama_id
    where lower(coalesce(bi.status, 'new')) in ('qualified', 'won', 'lost')
  loop
    v_org_id := rec.org_id;
    v_email_norm := lower(trim(coalesce(rec.customer_email, '')));
    v_phone_norm := regexp_replace(coalesce(rec.customer_phone, ''), '[^0-9]+', '', 'g');

    select c.id into v_contact_id
    from public.crm_contacts c
    where c.panorama_id = rec.panorama_id
      and (
        (v_email_norm <> '' and c.email_norm = v_email_norm)
        or
        (v_phone_norm <> '' and c.phone_norm = v_phone_norm)
      )
    order by c.updated_at desc
    limit 1;

    if v_contact_id is null then
      insert into public.crm_contacts (
        org_id, panorama_id, full_name, email, phone, email_norm, phone_norm,
        source_interest_id, created_by, notes, created_at, updated_at
      )
      values (
        v_org_id,
        rec.panorama_id,
        coalesce(rec.customer_name, ''),
        coalesce(rec.customer_email, ''),
        coalesce(rec.customer_phone, ''),
        v_email_norm,
        v_phone_norm,
        rec.id,
        rec.submitted_by,
        '',
        v_now,
        v_now
      )
      returning id into v_contact_id;
    end if;

    update public.buy_interests
    set
      contact_id = coalesce(contact_id, v_contact_id),
      is_contacted = true,
      contacted_at = coalesce(contacted_at, updated_at, created_at),
      updated_at = coalesce(updated_at, v_now)
    where id = rec.id;

    if lower(coalesce(rec.status, 'new')) = 'won' then
      v_stage := 'won';
    elsif lower(coalesce(rec.status, 'new')) = 'lost' then
      v_stage := 'lost';
    else
      v_stage := 'negotiation';
    end if;

    if not exists (
      select 1 from public.crm_deals d
      where d.interest_id = rec.id
    ) then
      insert into public.crm_deals (
        org_id, panorama_id, interest_id, contact_id, title, stage, is_active,
        amount, currency, plots, project_name, notes, created_by, created_at, updated_at
      )
      values (
        v_org_id,
        rec.panorama_id,
        rec.id,
        v_contact_id,
        coalesce(rec.customer_name, 'Deal'),
        v_stage,
        case when v_stage in ('won', 'lost') then false else true end,
        '',
        'INR',
        coalesce(rec.plots, '[]'::jsonb),
        coalesce(rec.panorama_name, ''),
        coalesce(rec.notes, ''),
        rec.submitted_by,
        coalesce(rec.created_at, v_now),
        coalesce(rec.updated_at, v_now)
      );
    end if;
  end loop;
end $$;
