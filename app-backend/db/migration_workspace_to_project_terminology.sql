-- Migration: rename Workspace terminology to Project at the database metadata layer.
-- The application still uses the existing physical tables/columns:
--   public.workspaces, workspace_id, workspace_access, workspace_share_endpoints.
-- Do not rename those identifiers unless the application code is changed in the
-- same release. This migration is safe to run in Supabase SQL Editor.

begin;

-- Keep project-plan defaults aligned with the new product wording.
alter table if exists public.project_plans
  alter column name set default 'Project Plan';

-- Rename a few legacy/accidental index names to the stable workspace_* names.
-- These are metadata-only changes; table and column names stay unchanged.
do $$
begin
  if to_regclass('public.idx_workspace_access_user_Project') is not null
     and to_regclass('public.idx_workspace_access_user_workspace') is null then
    alter index public."idx_workspace_access_user_Project"
      rename to idx_workspace_access_user_workspace;
  end if;

  if to_regclass('public.idx_building_maps_Project') is not null
     and to_regclass('public.idx_building_maps_workspace') is null then
    alter index public."idx_building_maps_Project"
      rename to idx_building_maps_workspace;
  end if;

  if to_regclass('public.idx_project_plans_Project') is not null
     and to_regclass('public.idx_project_plans_workspace') is null then
    alter index public."idx_project_plans_Project"
      rename to idx_project_plans_workspace;
  end if;

  if to_regclass('public.idx_galleries_Project') is not null
     and to_regclass('public.idx_galleries_workspace') is null then
    alter index public."idx_galleries_Project"
      rename to idx_galleries_workspace;
  end if;

  if to_regclass('public.idx_workspace_access_client_member_Project') is not null
     and to_regclass('public.idx_workspace_access_client_member_workspace') is null then
    alter index public."idx_workspace_access_client_member_Project"
      rename to idx_workspace_access_client_member_workspace;
  end if;
end $$;

-- Database comments for admins browsing the schema.
comment on table public.workspaces is
  'Projects shown in the product UI. Physical name remains workspaces for backward compatibility.';

comment on column public.workspaces.name is
  'Project name shown in the product UI.';

comment on table public.workspace_access is
  'Project-level access grants. Physical name remains workspace_access for backward compatibility.';

comment on column public.workspace_access.workspace_id is
  'References the project stored in public.workspaces.';

comment on table public.workspace_share_endpoints is
  'Custom share endpoints for projects. Physical name remains workspace_share_endpoints for backward compatibility.';

comment on column public.workspace_share_endpoints.workspace_id is
  'References the project stored in public.workspaces.';

comment on column public.panoramas.workspace_id is
  'Optional project link. Physical column name remains workspace_id for backward compatibility.';

comment on column public.mobile_panoramas.workspace_id is
  'Optional project link. Physical column name remains workspace_id for backward compatibility.';

comment on column public.daynight_projects.workspace_id is
  'Optional project link. Physical column name remains workspace_id for backward compatibility.';

comment on column public.building_maps.workspace_id is
  'Optional project link. Physical column name remains workspace_id for backward compatibility.';

comment on column public.project_plans.workspace_id is
  'Optional project link. Physical column name remains workspace_id for backward compatibility.';

comment on column public.galleries.workspace_id is
  'Optional project link. Physical column name remains workspace_id for backward compatibility.';

commit;
