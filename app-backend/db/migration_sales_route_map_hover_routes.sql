-- Add independent hover-only routes so highways and other map overlays
-- can be drawn without linking them to specific route-map markers.

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
