-- ============================================================
-- Migration: Add Customer Portal fields to panoramas
-- ============================================================
-- Run in Supabase Plotted Development → SQL Editor → New query
-- Adds fields needed for the customer-facing project portal:
--   location, coordinates, RERA, launch date, builder, amenities, etc.

-- Location & Map fields
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS location_address text default '';
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS location_city text default '';
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS location_state text default '';
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS location_lat double precision;
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS location_lng double precision;
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS google_maps_link text default '';

-- Project details
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS rera_registration text default '';
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS launch_date date;
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS possession_date text default '';
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS builder_name text default '';
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS project_type text default 'residential';
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS total_area text default '';
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS description text default '';
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS amenities jsonb default '[]';

-- Visibility / publishing
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS is_published boolean default false;
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS brochure_url text default '';
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS contact_phone text default '';
ALTER TABLE public.panoramas ADD COLUMN IF NOT EXISTS contact_email text default '';

-- Indexes for portal queries
CREATE INDEX IF NOT EXISTS idx_panoramas_is_published ON public.panoramas(is_published) WHERE is_published = true;
CREATE INDEX IF NOT EXISTS idx_panoramas_location_city ON public.panoramas(location_city);
CREATE INDEX IF NOT EXISTS idx_panoramas_project_type ON public.panoramas(project_type);
CREATE INDEX IF NOT EXISTS idx_panoramas_launch_date ON public.panoramas(launch_date DESC);
CREATE INDEX IF NOT EXISTS idx_panoramas_builder_name ON public.panoramas(builder_name);
