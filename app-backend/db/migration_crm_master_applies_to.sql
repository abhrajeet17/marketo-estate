alter table public.crm_master_attributes
  add column if not exists applies_to text[] not null default '{interests}';

update public.crm_master_attributes
set applies_to = '{interests,deals}'
where field_key in ('lead_source', 'lead_status')
  and applies_to = '{interests}';

update public.crm_master_attributes
set applies_to = '{deals}'
where field_key = 'deal_stage'
  and applies_to = '{interests}';

update public.crm_master_attributes
set applies_to = '{interests,contacts}'
where field_key in ('state', 'country')
  and applies_to = '{interests}';

update public.crm_master_attributes
set applies_to = '{contacts}'
where field_key = 'title'
  and applies_to = '{interests}';

