-- Migration: Fix legacy Full View ref columns that were created with bigint
-- Day/Night projects and Project Plans use uuid primary keys, so the earlier
-- bigint columns could never store valid references. This migration clears any
-- unusable legacy numeric values, converts the columns to uuid, and adds the
-- intended foreign keys.

do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'full_view_tabs'
      and column_name = 'ref_daynight_id'
      and udt_name <> 'uuid'
  ) then
    update public.full_view_tabs
    set ref_daynight_id = null
    where ref_daynight_id is not null;

    alter table public.full_view_tabs
      alter column ref_daynight_id type uuid
      using nullif(ref_daynight_id::text, '')::uuid;
  end if;

  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'full_view_tabs'
      and column_name = 'ref_project_plan_id'
      and udt_name <> 'uuid'
  ) then
    update public.full_view_tabs
    set ref_project_plan_id = null
    where ref_project_plan_id is not null;

    alter table public.full_view_tabs
      alter column ref_project_plan_id type uuid
      using nullif(ref_project_plan_id::text, '')::uuid;
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.full_view_tabs'::regclass
      and conname = 'full_view_tabs_ref_daynight_id_fkey'
  ) then
    alter table public.full_view_tabs
      add constraint full_view_tabs_ref_daynight_id_fkey
      foreign key (ref_daynight_id)
      references public.daynight_projects(id)
      on delete set null;
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.full_view_tabs'::regclass
      and conname = 'full_view_tabs_ref_project_plan_id_fkey'
  ) then
    alter table public.full_view_tabs
      add constraint full_view_tabs_ref_project_plan_id_fkey
      foreign key (ref_project_plan_id)
      references public.project_plans(id)
      on delete set null;
  end if;
end $$;

create index if not exists idx_full_view_tabs_ref_daynight
  on public.full_view_tabs(ref_daynight_id);

create index if not exists idx_full_view_tabs_ref_project_plan
  on public.full_view_tabs(ref_project_plan_id);
