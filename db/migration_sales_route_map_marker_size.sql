-- Add per-marker size support so route-map pointers can be scaled
-- independently in the editor and public route-map view.

alter table if exists public.sales_route_map_markers
  add column if not exists marker_size double precision not null default 1;

update public.sales_route_map_markers
set marker_size = 1
where marker_size is null
   or marker_size < 0.6
   or marker_size > 2.4;

alter table if exists public.sales_route_map_markers
  drop constraint if exists sales_route_map_markers_marker_size_check;

alter table if exists public.sales_route_map_markers
  add constraint sales_route_map_markers_marker_size_check
  check (marker_size >= 0.6 and marker_size <= 2.4);
