-- Broker-owned CRM masters (independent from client masters)

alter table public.crm_master_attributes
  alter column client_id drop not null;

alter table public.crm_master_values
  alter column client_id drop not null;

alter table public.crm_master_attributes
  add column if not exists owner_user_id uuid;

alter table public.crm_master_values
  add column if not exists owner_user_id uuid;

alter table public.crm_master_attributes
  drop constraint if exists crm_master_attributes_client_id_field_key_key;

alter table public.crm_master_values
  drop constraint if exists crm_master_values_client_id_field_key_value_key;

alter table public.crm_master_attributes
  add constraint crm_master_attributes_scope_check check (
    (client_id is not null and owner_user_id is null)
    or (client_id is null and owner_user_id is not null)
  );

alter table public.crm_master_values
  add constraint crm_master_values_scope_check check (
    (client_id is not null and owner_user_id is null)
    or (client_id is null and owner_user_id is not null)
  );

create unique index if not exists idx_crm_master_attributes_client_field
  on public.crm_master_attributes (client_id, field_key)
  where owner_user_id is null and client_id is not null;

create unique index if not exists idx_crm_master_attributes_broker_field
  on public.crm_master_attributes (owner_user_id, field_key)
  where owner_user_id is not null;

create unique index if not exists idx_crm_master_values_client_field_value
  on public.crm_master_values (client_id, field_key, value)
  where owner_user_id is null and client_id is not null;

create unique index if not exists idx_crm_master_values_broker_field_value
  on public.crm_master_values (owner_user_id, field_key, value)
  where owner_user_id is not null;

create index if not exists idx_crm_master_attributes_broker
  on public.crm_master_attributes (owner_user_id, sort_order)
  where owner_user_id is not null;

create index if not exists idx_crm_master_values_broker_field
  on public.crm_master_values (owner_user_id, field_key, sort_order)
  where owner_user_id is not null;
