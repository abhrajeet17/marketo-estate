ALTER TABLE public.workspaces ADD COLUMN IF NOT EXISTS panaroma_menu_config jsonb default '{}';
