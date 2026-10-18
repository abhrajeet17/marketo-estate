-- ============================================================
-- Sales Flat 360 migration
-- Upload a flat 360 strip image and render horizontal drag view.
-- ============================================================

create table if not exists public.sales_flat360_views (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  org_id uuid references public.organizations(id) on delete set null,
  workspace_id uuid references public.workspaces(id) on delete set null,
  name text not null default 'Sales 360 View',
  image_filename text not null,
  image_width int not null default 0,
  image_height int not null default 0,
  share_token text unique,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_sales_flat360_views_user
  on public.sales_flat360_views(user_id);
create index if not exists idx_sales_flat360_views_workspace
  on public.sales_flat360_views(workspace_id);
create index if not exists idx_sales_flat360_views_share_token
  on public.sales_flat360_views(share_token);

-- Full View integration
do $$
begin
  if to_regclass('public.full_view_tabs') is not null then
    alter table public.full_view_tabs
      add column if not exists ref_sales_flat360_id uuid references public.sales_flat360_views(id) on delete set null;
    create index if not exists idx_full_view_tabs_ref_sales_flat360
      on public.full_view_tabs(ref_sales_flat360_id);
  end if;
end $$;

