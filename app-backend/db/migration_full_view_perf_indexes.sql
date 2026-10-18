-- Performance indexes for faster workspace dropdown + full view config/tab lookups
-- Run this in Supabase SQL Editor

create index if not exists idx_workspaces_user_updated
  on public.workspaces(user_id, updated_at desc);

create index if not exists idx_workspace_access_user_workspace
  on public.workspace_access(user_id, workspace_id);

do $$
begin
  if to_regclass('public.full_view_configs') is not null then
    execute 'create index if not exists idx_full_view_configs_workspace_active
             on public.full_view_configs(workspace_id, is_active)';
  end if;

  if to_regclass('public.full_view_tabs') is not null then
    execute 'create index if not exists idx_full_view_tabs_config_sort_visible
             on public.full_view_tabs(config_id, sort_order, is_visible)';
  end if;
end $$;
