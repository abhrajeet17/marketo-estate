-- Migration: performance indexes for User Access Management (UAM) APIs
-- Run in Supabase SQL Editor. These indexes support user/org listing,
-- client group membership, invite lookup, and access-management screens.

-- Profiles: org-scoped user lists, email lookup, and role filtering.
create index if not exists idx_profiles_org_created_at
  on public.profiles(org_id, created_at desc);

create index if not exists idx_profiles_org_role_created_at
  on public.profiles(org_id, role, created_at desc);

create index if not exists idx_profiles_email
  on public.profiles(email);

create index if not exists idx_profiles_lower_email
  on public.profiles(lower(email));

-- User invites: admin invite history by org.
create index if not exists idx_user_invites_org_created_at
  on public.user_invites(org_id, created_at desc);

create index if not exists idx_user_invites_org_status_created_at
  on public.user_invites(org_id, status, created_at desc);

-- Client groups: org dashboards and name-ordered lists.
create index if not exists idx_clients_org_name
  on public.clients(org_id, name);

create index if not exists idx_clients_org_created_at
  on public.clients(org_id, created_at desc);

-- Client members: membership checks, member lists, role filters, and counts.
create index if not exists idx_client_members_client_created_at
  on public.client_members(client_id, created_at);

create index if not exists idx_client_members_client_role
  on public.client_members(client_id, member_role);

create index if not exists idx_client_members_user_role_client
  on public.client_members(user_id, member_role, client_id);

-- Client team invites: invite reuse/history and public token lookup.
create index if not exists idx_client_team_invites_client_email_created_at
  on public.client_team_invites(client_id, email, created_at desc);

create index if not exists idx_client_team_invites_client_status_created_at
  on public.client_team_invites(client_id, status, created_at desc);

create index if not exists idx_client_team_invites_status_expires_at
  on public.client_team_invites(status, expires_at);

-- Access tables: UAM screens query by client_member_id and resource id.
create index if not exists idx_workspace_access_client_member_workspace
  on public.workspace_access(client_member_id, workspace_id);

create index if not exists idx_workspace_access_workspace_client_member
  on public.workspace_access(workspace_id, client_member_id);

create index if not exists idx_workspace_access_user_client_member_workspace
  on public.workspace_access(user_id, client_member_id, workspace_id);

create index if not exists idx_panorama_access_client_member_panorama
  on public.panorama_access(client_member_id, panorama_id);

create index if not exists idx_panorama_access_panorama_client_member
  on public.panorama_access(panorama_id, client_member_id);

create index if not exists idx_panorama_access_user_client_member_panorama
  on public.panorama_access(user_id, client_member_id, panorama_id);

-- Project lookup helpers: workspace-level panorama resolution.
create index if not exists idx_panoramas_workspace_id_id
  on public.panoramas(workspace_id, id);
