-- Add line-style controls for independent hover routes so each route can
-- render as continuous, dashed, or dotted in the editor and public view.

alter table public.sales_route_map_hover_routes
  add column if not exists line_style text not null default 'dashed';

update public.sales_route_map_hover_routes
set line_style = 'dashed'
where coalesce(trim(line_style), '') = '';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'sales_route_map_hover_routes_line_style_check'
  ) then
    alter table public.sales_route_map_hover_routes
      add constraint sales_route_map_hover_routes_line_style_check
      check (line_style in ('continuous', 'dashed', 'dotted'));
  end if;
end $$;
