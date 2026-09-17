-- Hotfix for older environments missing sales_route_map_markers.icon_key.
-- Safe to run multiple times.

do $$
begin
  if to_regclass('public.sales_route_map_markers') is not null then
    alter table public.sales_route_map_markers
      add column if not exists icon_key text;

    update public.sales_route_map_markers
       set icon_key = case
         when coalesce(marker_type, '') = 'main' then 'main-star'
         else 'plot-pin'
       end
     where coalesce(trim(icon_key), '') = '';

    alter table public.sales_route_map_markers
      alter column icon_key set default '';

    alter table public.sales_route_map_markers
      alter column icon_key set not null;
  end if;
end $$;
