-- ============================================================
-- Sales Route Maps migration
-- Upload map image -> place one main pointer + normal pointers
-- -> draw routes between pointers.
-- ============================================================

-- 1) Base map records
create table if not exists public.sales_route_maps (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  org_id uuid references public.organizations(id) on delete set null,
  workspace_id uuid references public.workspaces(id) on delete set null,
  name text not null default 'Sales Route Map',
  image_filename text not null,
  image_width int not null default 0,
  image_height int not null default 0,
  share_token text unique,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_sales_route_maps_user
  on public.sales_route_maps(user_id);
create index if not exists idx_sales_route_maps_workspace
  on public.sales_route_maps(workspace_id);
create index if not exists idx_sales_route_maps_share_token
  on public.sales_route_maps(share_token);

-- 2) Pointers on map (normalized x/y ratios in [0..1])
create table if not exists public.sales_route_map_markers (
  id uuid primary key default gen_random_uuid(),
  map_id uuid not null references public.sales_route_maps(id) on delete cascade,
  marker_type text not null default 'normal'
    check (marker_type in ('main', 'normal')),
  pointer_type text not null default 'landmark',
  label text not null default '',
  icon_key text not null default '',
  icon_color text not null default '#22d3ee',
  icon_look text not null default 'solid',
  marker_size double precision not null default 1
    check (marker_size >= 0.6 and marker_size <= 2.4),
  x_ratio double precision not null check (x_ratio >= 0 and x_ratio <= 1),
  y_ratio double precision not null check (y_ratio >= 0 and y_ratio <= 1),
  sort_order int not null default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table if exists public.sales_route_map_markers
  add column if not exists icon_key text not null default '';

alter table if exists public.sales_route_map_markers
  add column if not exists pointer_type text not null default 'landmark';

alter table if exists public.sales_route_map_markers
  add column if not exists icon_color text not null default '#22d3ee';

alter table if exists public.sales_route_map_markers
  add column if not exists icon_look text not null default 'solid';

alter table if exists public.sales_route_map_markers
  add column if not exists marker_size double precision not null default 1;

alter table if exists public.sales_route_map_markers
  drop constraint if exists sales_route_map_markers_pointer_type_check;

alter table if exists public.sales_route_map_markers
  add constraint sales_route_map_markers_pointer_type_check
  check (
    pointer_type in (
      'project', 'landmark', 'residence', 'school', 'college',
      'hospital', 'clinic', 'pharmacy', 'airport', 'railway_station',
      'metro_station', 'bus_stop', 'petrol_pump', 'mall', 'market',
      'bank', 'office', 'restaurant', 'hotel', 'gym', 'park', 'garden',
      'stadium', 'temple', 'church', 'mosque', 'police_station',
      'industrial_area'
    )
  );

alter table if exists public.sales_route_map_markers
  drop constraint if exists sales_route_map_markers_icon_look_check;

alter table if exists public.sales_route_map_markers
  add constraint sales_route_map_markers_icon_look_check
  check (icon_look in ('solid', 'soft', 'outline', 'glass', 'light'));

alter table if exists public.sales_route_map_markers
  drop constraint if exists sales_route_map_markers_marker_size_check;

alter table if exists public.sales_route_map_markers
  add constraint sales_route_map_markers_marker_size_check
  check (marker_size >= 0.6 and marker_size <= 2.4);

create index if not exists idx_sales_route_map_markers_map
  on public.sales_route_map_markers(map_id);
create index if not exists idx_sales_route_map_markers_map_sort
  on public.sales_route_map_markers(map_id, sort_order);
create index if not exists idx_sales_route_map_markers_map_type
  on public.sales_route_map_markers(map_id, marker_type);
create index if not exists idx_sales_route_map_markers_map_pointer_type
  on public.sales_route_map_markers(map_id, pointer_type);

-- One main marker maximum per map.
create unique index if not exists uq_sales_route_map_one_main
  on public.sales_route_map_markers(map_id)
  where marker_type = 'main';

-- 3) Drawn routes/poly-lines between markers
create table if not exists public.sales_route_map_routes (
  id uuid primary key default gen_random_uuid(),
  map_id uuid not null references public.sales_route_maps(id) on delete cascade,
  from_marker_id uuid not null references public.sales_route_map_markers(id) on delete cascade,
  to_marker_id uuid not null references public.sales_route_map_markers(id) on delete cascade,
  path_points jsonb not null default '[]',
  color text not null default '#162338',
  line_width int not null default 3 check (line_width >= 1 and line_width <= 12),
  line_style text not null default 'dashed' check (line_style in ('continuous', 'dashed', 'dotted')),
  distance_km double precision check (distance_km is null or distance_km >= 0),
  sort_order int not null default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  check (from_marker_id <> to_marker_id),
  unique(map_id, from_marker_id, to_marker_id)
);

create index if not exists idx_sales_route_map_routes_map
  on public.sales_route_map_routes(map_id);
create index if not exists idx_sales_route_map_routes_map_sort
  on public.sales_route_map_routes(map_id, sort_order);
create index if not exists idx_sales_route_map_routes_from_marker
  on public.sales_route_map_routes(from_marker_id);
create index if not exists idx_sales_route_map_routes_to_marker
  on public.sales_route_map_routes(to_marker_id);

-- 4) Independent hover-only routes such as highways
create table if not exists public.sales_route_map_hover_routes (
  id uuid primary key default gen_random_uuid(),
  map_id uuid not null references public.sales_route_maps(id) on delete cascade,
  label text not null default '',
  path_points jsonb not null default '[]',
  color text not null default '#facc15',
  line_width int not null default 4 check (line_width >= 1 and line_width <= 12),
  line_style text not null default 'dashed' check (line_style in ('continuous', 'dashed', 'dotted')),
  sort_order int not null default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_sales_route_map_hover_routes_map
  on public.sales_route_map_hover_routes(map_id);
create index if not exists idx_sales_route_map_hover_routes_map_sort
  on public.sales_route_map_hover_routes(map_id, sort_order);

-- 5) Full View integration
do $$
begin
  if to_regclass('public.full_view_tabs') is not null then
    alter table public.full_view_tabs
      add column if not exists ref_sales_map_id uuid references public.sales_route_maps(id) on delete set null;
    create index if not exists idx_full_view_tabs_ref_sales_map
      on public.full_view_tabs(ref_sales_map_id);
  end if;
end $$;
