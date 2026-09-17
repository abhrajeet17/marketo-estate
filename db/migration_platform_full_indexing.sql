-- Migration: Platform-wide performance indexes
-- Goal: reduce API latency across CRM + non-CRM modules by aligning indexes
-- with real query patterns (filters + sort order + membership checks).
-- Safe to run multiple times.

-- Optional extension for faster ILIKE/contains search
create extension if not exists pg_trgm;

-- ---------------------------------------------------------------------------
-- Access control and membership lookups
-- ---------------------------------------------------------------------------
create index if not exists idx_workspace_access_user_workspace_type
  on public.workspace_access(user_id, workspace_id, access_type);

create index if not exists idx_panorama_access_user_panorama_type
  on public.panorama_access(user_id, panorama_id, access_type);

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'workspace_access'
      and column_name = 'client_member_id'
  ) then
    create index if not exists idx_workspace_access_client_member_workspace
      on public.workspace_access(client_member_id, workspace_id);
  end if;
end $$;

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'panorama_access'
      and column_name = 'client_member_id'
  ) then
    create index if not exists idx_panorama_access_client_member_panorama
      on public.panorama_access(client_member_id, panorama_id);
  end if;
end $$;

create index if not exists idx_profiles_email
  on public.profiles(email);

create index if not exists idx_profiles_org_role
  on public.profiles(org_id, role);

create index if not exists idx_client_members_user_client_role
  on public.client_members(user_id, client_id, member_role);

create index if not exists idx_client_members_client_role_created
  on public.client_members(client_id, member_role, created_at desc);

create index if not exists idx_clients_org_name
  on public.clients(org_id, name);

create index if not exists idx_client_team_invites_client_email_created
  on public.client_team_invites(client_id, email, created_at desc);

create index if not exists idx_client_team_invites_client_status_created
  on public.client_team_invites(client_id, status, created_at desc);

-- ---------------------------------------------------------------------------
-- Core workspace / panorama / plot paths
-- ---------------------------------------------------------------------------
create index if not exists idx_workspaces_user_updated
  on public.workspaces(user_id, updated_at desc);

create index if not exists idx_panoramas_user_updated
  on public.panoramas(user_id, updated_at desc);

create index if not exists idx_panoramas_workspace_is360
  on public.panoramas(workspace_id, is_360);

create index if not exists idx_mobile_panoramas_parent_id_id
  on public.mobile_panoramas(panorama_parent_id, id);

create index if not exists idx_plots_panorama_created
  on public.plots(panorama_id, created_at);

create index if not exists idx_plot_markers_plot_created
  on public.plot_markers(plot_id, created_at);

-- ---------------------------------------------------------------------------
-- Feature modules (day/night, floor plans, building maps, galleries, earth)
-- ---------------------------------------------------------------------------
do $$
begin
  if to_regclass('public.daynight_projects') is not null then
    execute 'create index if not exists idx_daynight_projects_user_created on public.daynight_projects(user_id, created_at desc)';
    execute 'create index if not exists idx_daynight_projects_user_workspace_created on public.daynight_projects(user_id, workspace_id, created_at desc)';
  end if;

  if to_regclass('public.floor_plan_catalogues') is not null then
    execute 'create index if not exists idx_floor_plan_catalogues_user_created on public.floor_plan_catalogues(user_id, created_at desc)';
  end if;

  if to_regclass('public.floor_plan_items') is not null then
    execute 'create index if not exists idx_floor_plan_items_catalogue_sort_created on public.floor_plan_items(catalogue_id, sort_order, created_at)';
  end if;

  if to_regclass('public.building_maps') is not null then
    execute 'create index if not exists idx_building_maps_user_created on public.building_maps(user_id, created_at desc)';
  end if;

  if to_regclass('public.building_map_images') is not null then
    execute 'create index if not exists idx_building_map_images_map_sort_created on public.building_map_images(building_map_id, sort_order, created_at)';
  end if;

  if to_regclass('public.building_zones') is not null then
    if exists (
      select 1
      from information_schema.columns
      where table_schema = 'public'
        and table_name = 'building_zones'
        and column_name = 'building_map_id'
    ) and exists (
      select 1
      from information_schema.columns
      where table_schema = 'public'
        and table_name = 'building_zones'
        and column_name = 'floor_number'
    ) and exists (
      select 1
      from information_schema.columns
      where table_schema = 'public'
        and table_name = 'building_zones'
        and column_name = 'sort_order'
    ) then
      execute 'create index if not exists idx_building_zones_map_floor_sort on public.building_zones(building_map_id, floor_number, sort_order)';
    end if;

    if exists (
      select 1
      from information_schema.columns
      where table_schema = 'public'
        and table_name = 'building_zones'
        and column_name = 'image_id'
    ) and exists (
      select 1
      from information_schema.columns
      where table_schema = 'public'
        and table_name = 'building_zones'
        and column_name = 'floor_number'
    ) and exists (
      select 1
      from information_schema.columns
      where table_schema = 'public'
        and table_name = 'building_zones'
        and column_name = 'sort_order'
    ) then
      execute 'create index if not exists idx_building_zones_image_floor_sort on public.building_zones(image_id, floor_number, sort_order)';
    end if;
  end if;

  if to_regclass('public.project_plans') is not null then
    execute 'create index if not exists idx_project_plans_user_created on public.project_plans(user_id, created_at desc)';
  end if;

  if to_regclass('public.project_plan_maps') is not null then
    execute 'create index if not exists idx_project_plan_maps_plan_sort on public.project_plan_maps(project_plan_id, sort_order)';
  end if;

  if to_regclass('public.galleries') is not null then
    execute 'create index if not exists idx_galleries_user_created on public.galleries(user_id, created_at desc)';
    execute 'create index if not exists idx_galleries_user_workspace_created on public.galleries(user_id, workspace_id, created_at desc)';
  end if;

  if to_regclass('public.gallery_items') is not null then
    execute 'create index if not exists idx_gallery_items_gallery_sort_created on public.gallery_items(gallery_id, sort_order, created_at)';
  end if;

  if to_regclass('public.earth_views') is not null then
    execute 'create index if not exists idx_earth_views_user_created on public.earth_views(user_id, created_at desc)';
  end if;

  if to_regclass('public.earth_view_plots') is not null then
    execute 'create index if not exists idx_earth_view_plots_view_sort_created on public.earth_view_plots(earth_view_id, sort_order, created_at)';
  end if;

  if to_regclass('public.earth_view_markers') is not null then
    execute 'create index if not exists idx_earth_view_markers_view_created on public.earth_view_markers(earth_view_id, created_at)';
  end if;
end $$;

-- Full view module (created in migration_full_view.sql)
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'public'
      and table_name = 'full_view_configs'
  ) then
    create index if not exists idx_full_view_configs_user_workspace
      on public.full_view_configs(user_id, workspace_id);
  end if;
end $$;

do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'public'
      and table_name = 'full_view_tabs'
  ) then
    create index if not exists idx_full_view_tabs_config_visible_sort
      on public.full_view_tabs(config_id, is_visible, sort_order);
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- CRM + lead workflows (cross-module latency)
-- ---------------------------------------------------------------------------
create index if not exists idx_buy_interests_client_status_created
  on public.buy_interests(client_id, status, created_at desc);

create index if not exists idx_buy_interests_client_contacted_created
  on public.buy_interests(client_id, is_contacted, created_at desc);

create index if not exists idx_crm_contacts_client_panorama_updated
  on public.crm_contacts(client_id, panorama_id, updated_at desc);

create index if not exists idx_crm_deals_client_stage_updated
  on public.crm_deals(client_id, stage, updated_at desc);

create index if not exists idx_crm_deals_client_panorama_updated
  on public.crm_deals(client_id, panorama_id, updated_at desc);

create index if not exists idx_crm_deal_quotes_deal_created
  on public.crm_deal_quotes(deal_id, created_at desc);

create index if not exists idx_crm_deals_active_client_updated
  on public.crm_deals(client_id, updated_at desc)
  where is_active = true;

create index if not exists idx_buy_interests_uncontacted_client_created
  on public.buy_interests(client_id, created_at desc)
  where is_contacted = false;

-- ---------------------------------------------------------------------------
-- Text search indexes (ILIKE paths)
-- ---------------------------------------------------------------------------
do $$
begin
  if to_regclass('public.floor_plan_catalogues') is not null then
    execute 'create index if not exists idx_floor_plan_catalogues_name_trgm on public.floor_plan_catalogues using gin (name gin_trgm_ops)';
  end if;
end $$;

create index if not exists idx_crm_contacts_full_name_trgm
  on public.crm_contacts using gin (full_name gin_trgm_ops);

create index if not exists idx_crm_contacts_email_trgm
  on public.crm_contacts using gin (email gin_trgm_ops);

create index if not exists idx_crm_contacts_phone_trgm
  on public.crm_contacts using gin (phone gin_trgm_ops);

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'crm_deals'
      and column_name = 'title'
  ) then
    create index if not exists idx_crm_deals_title_trgm
      on public.crm_deals using gin (title gin_trgm_ops);
  end if;
end $$;

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'crm_deals'
      and column_name = 'project_name'
  ) then
    create index if not exists idx_crm_deals_project_name_trgm
      on public.crm_deals using gin (project_name gin_trgm_ops);
  end if;
end $$;
