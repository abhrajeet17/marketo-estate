ALTER TABLE public.plot_markers
    ADD COLUMN IF NOT EXISTS rotation_x double precision default 0,
    ADD COLUMN IF NOT EXISTS rotation_y double precision default 0,
    ADD COLUMN IF NOT EXISTS rotation_z double precision default 0;

