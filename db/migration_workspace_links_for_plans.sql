-- Migration: add workspace linking support to building maps and project plans

alter table if exists public.building_maps
  add column if not exists workspace_id uuid references public.workspaces(id) on delete set null;

create index if not exists idx_building_maps_workspace on public.building_maps(workspace_id);

alter table if exists public.project_plans
  add column if not exists workspace_id uuid references public.workspaces(id) on delete set null;

create index if not exists idx_project_plans_workspace on public.project_plans(workspace_id);
