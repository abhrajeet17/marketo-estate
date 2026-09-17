-- Add semantic pointer types to route-map markers so typed icons and
-- distinct-type filters can work without changing the existing UI flow.

alter table if exists public.sales_route_map_markers
  add column if not exists pointer_type text not null default 'landmark';

update public.sales_route_map_markers
set pointer_type = case
  when coalesce(marker_type, '') = 'main' then 'project'
  when coalesce(icon_key, '') = 'plot-gate' then 'residence'
  when coalesce(icon_key, '') = 'plot-tree' then 'park'
  when coalesce(icon_key, '') = 'plot-office' then 'office'
  when coalesce(icon_key, '') = 'poi-school' then 'school'
  when coalesce(icon_key, '') = 'poi-college' then 'college'
  when coalesce(icon_key, '') = 'poi-hospital' then 'hospital'
  when coalesce(icon_key, '') = 'poi-clinic' then 'clinic'
  when coalesce(icon_key, '') = 'poi-pharmacy' then 'pharmacy'
  when coalesce(icon_key, '') = 'poi-airport' then 'airport'
  when coalesce(icon_key, '') = 'poi-railway' then 'railway_station'
  when coalesce(icon_key, '') = 'poi-metro' then 'metro_station'
  when coalesce(icon_key, '') = 'poi-bus' then 'bus_stop'
  when coalesce(icon_key, '') = 'poi-petrol' then 'petrol_pump'
  when coalesce(icon_key, '') = 'poi-mall' then 'mall'
  when coalesce(icon_key, '') = 'poi-market' then 'market'
  when coalesce(icon_key, '') = 'poi-bank' then 'bank'
  when coalesce(icon_key, '') = 'poi-restaurant' then 'restaurant'
  when coalesce(icon_key, '') = 'poi-hotel' then 'hotel'
  when coalesce(icon_key, '') = 'poi-gym' then 'gym'
  when coalesce(icon_key, '') = 'poi-park' then 'park'
  when coalesce(icon_key, '') = 'poi-garden' then 'garden'
  when coalesce(icon_key, '') = 'poi-stadium' then 'stadium'
  when coalesce(icon_key, '') = 'poi-temple' then 'temple'
  when coalesce(icon_key, '') = 'poi-church' then 'church'
  when coalesce(icon_key, '') = 'poi-mosque' then 'mosque'
  when coalesce(icon_key, '') = 'poi-police' then 'police_station'
  when coalesce(icon_key, '') = 'poi-residence' then 'residence'
  when coalesce(icon_key, '') = 'poi-industrial' then 'industrial_area'
  else case
    when coalesce(marker_type, '') = 'main' then 'project'
    else 'landmark'
  end
end
where pointer_type is null
   or btrim(pointer_type) = ''
   or coalesce(marker_type, '') = 'main'
   or (
     coalesce(pointer_type, '') = 'landmark'
     and coalesce(icon_key, '') in (
       'plot-gate', 'plot-tree', 'plot-office',
       'poi-school', 'poi-college', 'poi-hospital', 'poi-clinic', 'poi-pharmacy',
       'poi-airport', 'poi-railway', 'poi-metro', 'poi-bus', 'poi-petrol',
       'poi-mall', 'poi-market', 'poi-bank', 'poi-restaurant', 'poi-hotel',
       'poi-gym', 'poi-park', 'poi-garden', 'poi-stadium', 'poi-temple',
       'poi-church', 'poi-mosque', 'poi-police', 'poi-residence',
       'poi-industrial'
     )
   );

create index if not exists idx_sales_route_map_markers_map_pointer_type
  on public.sales_route_map_markers(map_id, pointer_type);
