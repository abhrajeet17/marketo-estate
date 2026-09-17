-- Add per-marker appearance fields so route-map pointers can have
-- customizable color and look presets across editor and public view.

alter table if exists public.sales_route_map_markers
  add column if not exists icon_color text not null default '#22d3ee';

alter table if exists public.sales_route_map_markers
  add column if not exists icon_look text not null default 'solid';

update public.sales_route_map_markers
set icon_color = case
  when coalesce(marker_type, '') = 'main' then '#f97316'
  else '#22d3ee'
end
where icon_color is null
   or btrim(icon_color) = '';

update public.sales_route_map_markers
set icon_look = 'solid'
where icon_look is null
   or btrim(icon_look) = '';

alter table if exists public.sales_route_map_markers
  drop constraint if exists sales_route_map_markers_icon_look_check;

alter table if exists public.sales_route_map_markers
  add constraint sales_route_map_markers_icon_look_check
  check (icon_look in ('solid', 'soft', 'outline', 'glass', 'light'));
