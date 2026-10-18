-- Migration: link earth views to a project (workspace), like every other Sales Tool resource.
-- Additive and data-preserving: a nullable column + index; existing rows keep workspace_id = NULL.
-- earth_view_service.py already writes/filters this column (and falls back when it is missing).
-- Safe to re-run.

alter table public.earth_views
  add column if not exists workspace_id uuid references public.workspaces (id) on delete set null;

create index if not exists idx_earth_views_workspace_id_fk on public.earth_views (workspace_id);
