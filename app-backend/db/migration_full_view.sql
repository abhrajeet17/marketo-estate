-- Migration: Full View Creator
-- Adds full_view_configs and full_view_tabs tables
-- Run this in Supabase SQL Editor

-- full_view_configs: one config per workspace
create table if not exists public.full_view_configs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  org_id uuid references public.organizations(id) on delete set null,
  user_id uuid not null references auth.users(id) on delete cascade,
  is_active boolean not null default true,
  style jsonb not null default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(workspace_id)
);

create index if not exists idx_full_view_configs_workspace on public.full_view_configs(workspace_id);
create index if not exists idx_full_view_configs_org on public.full_view_configs(org_id);

-- full_view_tabs: individual tabs within a full view config
create table if not exists public.full_view_tabs (
  id uuid primary key default gen_random_uuid(),
  config_id uuid not null references public.full_view_configs(id) on delete cascade,
  icon text not null default 'ph:house',
  name text not null,
  -- tab_type values: 360_pano | daynight | floor_plan | gallery | project_plan |
  --                  sales_map | drone_view | location | highlights | amenities |
  --                  brochure | link | custom
  tab_type text not null default '360_pano',
  -- Content references (only one set depending on type)
  ref_panorama_id bigint,
  ref_daynight_id uuid references public.daynight_projects(id) on delete set null,
  ref_floor_plan_id uuid,
  ref_gallery_id uuid,
  ref_project_plan_id uuid references public.project_plans(id) on delete set null,
  ref_sales_map_id uuid,
  -- Generic key/value store for custom type data (e.g. {"url": "https://..."})
  content_data jsonb not null default '{}',
  sort_order integer not null default 0,
  is_visible boolean not null default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_full_view_tabs_config on public.full_view_tabs(config_id);
create index if not exists idx_full_view_tabs_sort on public.full_view_tabs(config_id, sort_order);

-- Backfill for existing deployments where full_view_tabs was created earlier
alter table public.full_view_tabs
  add column if not exists ref_sales_map_id uuid;

create index if not exists idx_full_view_tabs_ref_sales_map on public.full_view_tabs(ref_sales_map_id);

-- Enable RLS
alter table public.full_view_configs enable row level security;
alter table public.full_view_tabs enable row level security;

-- RLS: full_view_configs
create policy "Users can view own full_view_configs"
  on public.full_view_configs for select
  using (auth.uid() = user_id);
create policy "Users can insert own full_view_configs"
  on public.full_view_configs for insert
  with check (auth.uid() = user_id);
create policy "Users can update own full_view_configs"
  on public.full_view_configs for update
  using (auth.uid() = user_id);
create policy "Users can delete own full_view_configs"
  on public.full_view_configs for delete
  using (auth.uid() = user_id);

-- RLS: full_view_tabs
create policy "Users can view own full_view_tabs"
  on public.full_view_tabs for select
  using (
    exists (
      select 1 from public.full_view_configs c
      where c.id = config_id and c.user_id = auth.uid()
    )
  );
create policy "Users can insert own full_view_tabs"
  on public.full_view_tabs for insert
  with check (
    exists (
      select 1 from public.full_view_configs c
      where c.id = config_id and c.user_id = auth.uid()
    )
  );
create policy "Users can update own full_view_tabs"
  on public.full_view_tabs for update
  using (
    exists (
      select 1 from public.full_view_configs c
      where c.id = config_id and c.user_id = auth.uid()
    )
  );
create policy "Users can delete own full_view_tabs"
  on public.full_view_tabs for delete
  using (
    exists (
      select 1 from public.full_view_configs c
      where c.id = config_id and c.user_id = auth.uid()
    )
  );
