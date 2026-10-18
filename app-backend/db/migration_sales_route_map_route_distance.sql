-- Add optional distance attribute (in km) to sales route map routes.
alter table if exists public.sales_route_map_routes
  add column if not exists distance_km double precision;

alter table if exists public.sales_route_map_routes
  drop constraint if exists sales_route_map_routes_distance_km_check;

alter table if exists public.sales_route_map_routes
  add constraint sales_route_map_routes_distance_km_check
  check (distance_km is null or distance_km >= 0);
