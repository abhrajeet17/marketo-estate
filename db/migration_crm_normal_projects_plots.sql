create table if not exists public.crm_normal_projects (
  id bigserial primary key,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  location text,
  description text,
  project_type text default 'residential',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_crm_normal_projects_owner_updated
  on public.crm_normal_projects(owner_user_id, updated_at desc);

create table if not exists public.crm_normal_plots (
  id bigserial primary key,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  project_id bigint references public.crm_normal_projects(id) on delete set null,
  project_name text not null,
  name text not null,
  area text,
  price text,
  status text default 'available',
  description text,
  panorama_id bigint,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_crm_normal_plots_owner_updated
  on public.crm_normal_plots(owner_user_id, updated_at desc);

create index if not exists idx_crm_normal_plots_owner_project
  on public.crm_normal_plots(owner_user_id, project_id);
