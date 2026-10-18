-- Migration: Add galleries and gallery_items tables
-- Run this in Supabase SQL Editor

-- 18) Galleries
create table if not exists public.galleries (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  org_id uuid references public.organizations(id) on delete set null,
  workspace_id uuid references public.workspaces(id) on delete set null,
  name text not null default 'Gallery',
  share_token text unique,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_galleries_user on public.galleries(user_id);
create index if not exists idx_galleries_workspace on public.galleries(workspace_id);
create index if not exists idx_galleries_share_token on public.galleries(share_token);

-- 19) Gallery Items (images or videos within a gallery)
create table if not exists public.gallery_items (
  id uuid primary key default gen_random_uuid(),
  gallery_id uuid not null references public.galleries(id) on delete cascade,
  name text not null,
  media_type text not null default 'image',  -- 'image' or 'video'
  is_360 boolean not null default false,
  filename text not null,
  file_size_bytes bigint default 0,
  media_width int default 0,
  media_height int default 0,
  sort_order int not null default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_gallery_items_gallery on public.gallery_items(gallery_id);
create index if not exists idx_gallery_items_sort_order on public.gallery_items(gallery_id, sort_order);
create index if not exists idx_gallery_items_gallery_is360 on public.gallery_items(gallery_id, is_360);

-- Enable RLS
alter table public.galleries enable row level security;
alter table public.gallery_items enable row level security;

-- RLS policies for galleries
create policy "Users can view own galleries"
  on public.galleries for select using (auth.uid() = user_id);
create policy "Users can insert own galleries"
  on public.galleries for insert with check (auth.uid() = user_id);
create policy "Users can update own galleries"
  on public.galleries for update using (auth.uid() = user_id);
create policy "Users can delete own galleries"
  on public.galleries for delete using (auth.uid() = user_id);

-- RLS policies for gallery_items
create policy "Users can view own gallery items"
  on public.gallery_items for select using (
    exists (select 1 from public.galleries g where g.id = gallery_id and g.user_id = auth.uid())
  );
create policy "Users can insert own gallery items"
  on public.gallery_items for insert with check (
    exists (select 1 from public.galleries g where g.id = gallery_id and g.user_id = auth.uid())
  );
create policy "Users can update own gallery items"
  on public.gallery_items for update using (
    exists (select 1 from public.galleries g where g.id = gallery_id and g.user_id = auth.uid())
  );
create policy "Users can delete own gallery items"
  on public.gallery_items for delete using (
    exists (select 1 from public.galleries g where g.id = gallery_id and g.user_id = auth.uid())
  );
