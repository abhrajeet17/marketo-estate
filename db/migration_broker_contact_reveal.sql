-- Migration: broker-referred lead contact reveal gate
-- Run this in Supabase SQL Editor

alter table public.buy_interests
  add column if not exists contact_revealed_at timestamptz;

create index if not exists idx_buy_interests_reference_revealed
  on public.buy_interests(reference_user_id, contact_revealed_at)
  where reference_user_id is not null;