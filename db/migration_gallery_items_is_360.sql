-- Migration: Add explicit 360 flag on gallery items
-- Run this in Supabase SQL Editor

alter table if exists public.gallery_items
  add column if not exists is_360 boolean;

alter table if exists public.gallery_items
  alter column is_360 set default false;

-- Keep all existing rows as non-360 initially; update manually from UI later.
update public.gallery_items
set is_360 = false;

alter table if exists public.gallery_items
  alter column is_360 set not null;

create index if not exists idx_gallery_items_gallery_is360
  on public.gallery_items(gallery_id, is_360);
