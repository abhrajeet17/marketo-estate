alter table if exists public.buy_interests
  add column if not exists custom_fields jsonb not null default '{}'::jsonb;

alter table if exists public.crm_contacts
  add column if not exists custom_fields jsonb not null default '{}'::jsonb;

alter table if exists public.crm_deals
  add column if not exists custom_fields jsonb not null default '{}'::jsonb;

alter table if exists public.crm_normal_projects
  add column if not exists custom_fields jsonb not null default '{}'::jsonb;

alter table if exists public.crm_normal_plots
  add column if not exists custom_fields jsonb not null default '{}'::jsonb;
