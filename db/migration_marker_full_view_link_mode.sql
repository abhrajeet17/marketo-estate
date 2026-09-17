ALTER TABLE public.plot_markers
  ADD COLUMN IF NOT EXISTS link_mode text;

UPDATE public.plot_markers
SET link_mode = COALESCE(NULLIF(TRIM(link_mode), ''), 'panorama')
WHERE link_mode IS NULL OR TRIM(link_mode) = '';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'plot_markers_link_mode_check'
  ) THEN
    ALTER TABLE public.plot_markers
      ADD CONSTRAINT plot_markers_link_mode_check
      CHECK (link_mode IN ('panorama', 'full_view'));
  END IF;
END $$;

ALTER TABLE public.plot_markers
  ALTER COLUMN link_mode SET DEFAULT 'panorama',
  ALTER COLUMN link_mode SET NOT NULL;
