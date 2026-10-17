-- ============================================================
-- Building Plan links – migration
--
-- Lets a zone drawn on a building map open another building map
-- (aerial -> tower -> floor -> floor plan), carries the info shown
-- on the customer view card (floors, apartments, BHK, size, unit
-- status), and stores per-map view settings (level, RERA, interest).
--
-- Also creates building_map_images / building_zones.image_id, which
-- the code already queries but older databases never received.
--
-- Safe to re-run.
-- ============================================================

-- 1) Multiple views per building map (was in schema.sql only)
create table if not exists public.building_map_images (
  id uuid primary key default gen_random_uuid(),
  building_map_id uuid not null references public.building_maps(id) on delete cascade,
  name text not null default 'View',
  image_filename text not null,
  image_width int default 0,
  image_height int default 0,
  sort_order int default 0,
  created_at timestamptz default now()
);
create index if not exists idx_building_map_images_map on public.building_map_images(building_map_id);
create index if not exists idx_building_map_images_sort on public.building_map_images(building_map_id, sort_order);

alter table public.building_zones
  add column if not exists image_id uuid references public.building_map_images(id) on delete cascade;
create index if not exists idx_building_zones_image on public.building_zones(image_id);

-- 2) Zone -> building map link + info card
alter table public.building_zones
  add column if not exists linked_building_map_id uuid references public.building_maps(id) on delete set null;
alter table public.building_zones
  add column if not exists link_type text not null default '';
alter table public.building_zones
  add column if not exists meta jsonb not null default '{}'::jsonb;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'building_zones_link_type_check'
  ) then
    alter table public.building_zones
      add constraint building_zones_link_type_check
      check (link_type in ('', 'panorama', 'floor_plan', 'building_map'));
  end if;
end $$;

create index if not exists idx_building_zones_linked_building_map on public.building_zones(linked_building_map_id);

-- Back-fill link_type for zones created before this migration.
update public.building_zones set link_type = 'panorama'
  where link_type = '' and linked_panorama_id is not null;
update public.building_zones set link_type = 'floor_plan'
  where link_type = '' and linked_floor_plan_item_id is not null;

-- 3) Per-map customer view settings (level, brand, RERA, show interest)
alter table public.building_maps
  add column if not exists view_config jsonb not null default '{}'::jsonb;

notify pgrst, 'reload schema';
