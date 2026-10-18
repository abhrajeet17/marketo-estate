-- Migration: index every foreign key, and evaluate auth.uid() once per statement in RLS policies.
-- Additive and data-preserving: only creates indexes and rewrites policies to the identical rule.
-- Safe to re-run (IF NOT EXISTS / ALTER POLICY).

-- ---------------------------------------------------------------------------
-- 1) Covering indexes for foreign keys flagged by the Supabase performance advisor
--    (lint 0001_unindexed_foreign_keys): speeds up joins and ON DELETE cascades / SET NULL.
-- ---------------------------------------------------------------------------
create index if not exists idx_building_maps_org_id_fk on public.building_maps (org_id);
create index if not exists idx_buy_interests_contact_id_fk on public.buy_interests (contact_id);
create index if not exists idx_buy_interests_submitted_by_fk on public.buy_interests (submitted_by);
create index if not exists idx_client_members_invited_by_fk on public.client_members (invited_by);
create index if not exists idx_client_team_invites_accepted_user_id_fk on public.client_team_invites (accepted_user_id);
create index if not exists idx_client_team_invites_invited_by_fk on public.client_team_invites (invited_by);
create index if not exists idx_clients_created_by_fk on public.clients (created_by);
create index if not exists idx_crm_contacts_created_by_fk on public.crm_contacts (created_by);
create index if not exists idx_crm_contacts_source_interest_id_fk on public.crm_contacts (source_interest_id);
create index if not exists idx_crm_deal_quotes_created_by_fk on public.crm_deal_quotes (created_by);
create index if not exists idx_crm_deal_quotes_template_id_fk on public.crm_deal_quotes (template_id);
create index if not exists idx_crm_deals_created_by_fk on public.crm_deals (created_by);
create index if not exists idx_crm_leads_converted_by_fk on public.crm_leads (converted_by);
create index if not exists idx_crm_leads_org_id_fk on public.crm_leads (org_id);
create index if not exists idx_crm_normal_plots_project_id_fk on public.crm_normal_plots (project_id);
create index if not exists idx_crm_quote_templates_created_by_fk on public.crm_quote_templates (created_by);
create index if not exists idx_floor_plan_catalogues_org_id_fk on public.floor_plan_catalogues (org_id);
create index if not exists idx_floor_plan_catalogues_workspace_id_fk on public.floor_plan_catalogues (workspace_id);
create index if not exists idx_galleries_org_id_fk on public.galleries (org_id);
create index if not exists idx_panorama_access_granted_by_fk on public.panorama_access (granted_by);
create index if not exists idx_project_plans_org_id_fk on public.project_plans (org_id);
create index if not exists idx_sales_flat360_views_org_id_fk on public.sales_flat360_views (org_id);
create index if not exists idx_sales_route_maps_org_id_fk on public.sales_route_maps (org_id);
create index if not exists idx_user_invites_invited_user_id_fk on public.user_invites (invited_user_id);
create index if not exists idx_workspace_access_granted_by_fk on public.workspace_access (granted_by);
create index if not exists idx_workspace_share_endpoints_created_by_fk on public.workspace_share_endpoints (created_by);
create index if not exists idx_workspace_share_endpoints_updated_by_fk on public.workspace_share_endpoints (updated_by);

-- ---------------------------------------------------------------------------
-- 2) RLS: (select auth.uid()) instead of auth.uid() (lint 0003_auth_rls_initplan).
--    Same rule, evaluated once per statement instead of once per row.
-- ---------------------------------------------------------------------------
alter policy "Users can view own galleries" on public.galleries using ((select auth.uid()) = user_id);
alter policy "Users can insert own galleries" on public.galleries with check ((select auth.uid()) = user_id);
alter policy "Users can update own galleries" on public.galleries using ((select auth.uid()) = user_id);
alter policy "Users can delete own galleries" on public.galleries using ((select auth.uid()) = user_id);

alter policy "Users can view own gallery items" on public.gallery_items
  using (exists (select 1 from public.galleries g where g.id = gallery_items.gallery_id and g.user_id = (select auth.uid())));
alter policy "Users can insert own gallery items" on public.gallery_items
  with check (exists (select 1 from public.galleries g where g.id = gallery_items.gallery_id and g.user_id = (select auth.uid())));
alter policy "Users can update own gallery items" on public.gallery_items
  using (exists (select 1 from public.galleries g where g.id = gallery_items.gallery_id and g.user_id = (select auth.uid())));
alter policy "Users can delete own gallery items" on public.gallery_items
  using (exists (select 1 from public.galleries g where g.id = gallery_items.gallery_id and g.user_id = (select auth.uid())));

alter policy "Users can view own full_view_tabs" on public.full_view_tabs
  using (exists (select 1 from public.full_view_configs c where c.id = full_view_tabs.config_id and c.user_id = (select auth.uid())));
alter policy "Users can insert own full_view_tabs" on public.full_view_tabs
  with check (exists (select 1 from public.full_view_configs c where c.id = full_view_tabs.config_id and c.user_id = (select auth.uid())));
alter policy "Users can update own full_view_tabs" on public.full_view_tabs
  using (exists (select 1 from public.full_view_configs c where c.id = full_view_tabs.config_id and c.user_id = (select auth.uid())));
alter policy "Users can delete own full_view_tabs" on public.full_view_tabs
  using (exists (select 1 from public.full_view_configs c where c.id = full_view_tabs.config_id and c.user_id = (select auth.uid())));
