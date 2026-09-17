-- Migration: add style blob for Full View screen customization

alter table if exists public.full_view_configs
  add column if not exists style jsonb not null default '{}'::jsonb;

update public.full_view_configs
set style = '{}'::jsonb
where style is null;
