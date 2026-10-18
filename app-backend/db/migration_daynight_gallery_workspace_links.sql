-- Migration: Link Day/Night and Galleries to a project workspace
-- Run this in Supabase SQL Editor

alter table public.daynight_projects
  add column if not exists workspace_id uuid references public.workspaces(id) on delete set null;

create index if not exists idx_daynight_projects_workspace_id
  on public.daynight_projects(workspace_id);

alter table public.galleries
  add column if not exists workspace_id uuid references public.workspaces(id) on delete set null;

create index if not exists idx_galleries_workspace
  on public.galleries(workspace_id);

