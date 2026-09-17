-- Migration: CRM performance indexes for sub-200ms API targets
-- Safe to run multiple times.

-- Fast list/filter on buy interests
create index if not exists idx_buy_interests_panorama_created
  on public.buy_interests(panorama_id, created_at desc);

create index if not exists idx_buy_interests_panorama_contacted_created
  on public.buy_interests(panorama_id, is_contacted, created_at desc);

-- Fast list/filter on CRM contacts
create index if not exists idx_crm_contacts_panorama_updated
  on public.crm_contacts(panorama_id, updated_at desc);

create index if not exists idx_crm_contacts_org_email_norm
  on public.crm_contacts(org_id, email_norm);

create index if not exists idx_crm_contacts_org_phone_norm
  on public.crm_contacts(org_id, phone_norm);

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='crm_contacts' and column_name='client_id'
  ) then
    create index if not exists idx_crm_contacts_client_updated
      on public.crm_contacts(client_id, updated_at desc);
  end if;
end $$;

-- Fast list/filter on CRM deals
create index if not exists idx_crm_deals_panorama_updated
  on public.crm_deals(panorama_id, updated_at desc);

create index if not exists idx_crm_deals_panorama_stage_updated
  on public.crm_deals(panorama_id, stage, updated_at desc);

create index if not exists idx_crm_deals_interest_active
  on public.crm_deals(interest_id, is_active);

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='crm_deals' and column_name='client_id'
  ) then
    create index if not exists idx_crm_deals_client_updated
      on public.crm_deals(client_id, updated_at desc);
  end if;
  if exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='buy_interests' and column_name='client_id'
  ) then
    create index if not exists idx_buy_interests_client_created
      on public.buy_interests(client_id, created_at desc);
  end if;
end $$;

-- Access lookup acceleration used by CRM access resolver
create index if not exists idx_panorama_access_user_panorama
  on public.panorama_access(user_id, panorama_id);

create index if not exists idx_workspace_access_user_workspace
  on public.workspace_access(user_id, workspace_id);

create index if not exists idx_plot_lock_access_user_panorama
  on public.plot_lock_access(user_id, panorama_id);

create index if not exists idx_client_members_user_role_client
  on public.client_members(user_id, member_role, client_id);

create index if not exists idx_client_members_client_role_user
  on public.client_members(client_id, member_role, user_id);
