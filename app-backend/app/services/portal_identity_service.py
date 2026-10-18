"""
Portal identity: who the caller is and which portal capabilities they have.

One place resolves profile, organization and client-team membership so the
portal shell needs a single request (`GET /api/portal/me`) instead of chaining
`/api/org/me` -> `/api/crm/me`. Both legacy endpoints build their payloads from
the same resolver, which keeps the role rules in one spot.
"""
import threading
import time

from app.core.auth import get_profile
from app.services.org_service import slugify_org_name
from app.services.uam_reference_service import (
    CLIENT_MEMBER_ROLE_BROKER,
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    _is_broker_member_role,
    _normalize_client_member_role,
)

_TTL_SECONDS = 20
_CACHE_MAX = 2000
_cache = {}
_lock = threading.Lock()

PLATFORM_ADMIN_ROLES = ('admin', 'superadmin')
_TEAM_ROLES = (CLIENT_MEMBER_ROLE_CLIENT_ADMIN, CLIENT_MEMBER_ROLE_CLIENT_USER, CLIENT_MEMBER_ROLE_BROKER)


def invalidate_portal_identity(user_id=None):
    """Drop cached identity (all users, or one) after membership/profile changes."""
    with _lock:
        if user_id is None:
            _cache.clear()
        else:
            for key in [k for k in _cache if k[0] == str(user_id)]:
                _cache.pop(key, None)


def _cached(key):
    with _lock:
        entry = _cache.get(key)
    if entry and time.time() - entry[0] <= _TTL_SECONDS:
        return entry[1]
    return None


def _store(key, value):
    with _lock:
        if len(_cache) > _CACHE_MAX:
            _cache.clear()
        _cache[key] = (time.time(), value)


def _load_org(sb, org_id):
    if not org_id:
        return None
    try:
        rows = (
            sb.table('organizations')
            .select('id, name, accent_color, created_at, updated_at')
            .eq('id', org_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        return None
    if not rows:
        return None
    org = {k: (str(v) if k in ('created_at', 'updated_at') and v else v) for k, v in rows[0].items()}
    if org.get('name'):
        org['slug'] = slugify_org_name(org['name'])
    return org


def _load_memberships(sb, user_id):
    """Client-team roles and the ordered list of teams the user belongs to."""
    try:
        rows = sb.table('client_members').select('client_id, member_role').eq('user_id', str(user_id)).execute().data or []
    except Exception:
        rows = []
    roles = set()
    client_ids = []
    for row in rows:
        member_role = _normalize_client_member_role(row.get('member_role'))
        if _is_broker_member_role(member_role):
            roles.add(CLIENT_MEMBER_ROLE_BROKER)
        roles.add(member_role)
        client_id = str(row.get('client_id') or '').strip()
        if member_role in _TEAM_ROLES and client_id and client_id not in client_ids:
            client_ids.append(client_id)
    teams = []
    if client_ids:
        try:
            teams = sb.table('clients').select('id, name').in_('id', client_ids).order('name').execute().data or []
        except Exception:
            teams = []
    return roles, [
        {'id': str(t.get('id') or ''), 'name': str(t.get('name') or '').strip()}
        for t in teams if t.get('id')
    ]


def _has_direct_access(sb, user_id):
    """True when projects or panoramas were shared with the user personally (outside any client group)."""
    for table in ('workspace_access', 'panorama_access'):
        try:
            if sb.table(table).select('user_id').eq('user_id', str(user_id)).limit(1).execute().data:
                return True
        except Exception:
            return True  # never lock someone out on a failed lookup
    return False


def resolve_portal_identity(sb, user_id, role, *, crm_panorama_ids=None):
    """
    Return a dict describing the caller. `crm_panorama_ids` (optional) is the
    CRM scope resolver; when given, `has_crm_access` reflects real panorama scope.
    """
    key = (str(user_id), str(role or ''), bool(crm_panorama_ids))
    cached = _cached(key)
    if cached is not None:
        return dict(cached)

    profile = get_profile(sb, user_id) or {}
    profile_role = str(profile.get('role') or role or 'user').strip().lower()
    is_platform_admin = profile_role in PLATFORM_ADMIN_ROLES
    member_roles, teams = _load_memberships(sb, user_id)

    is_broker = CLIENT_MEMBER_ROLE_BROKER in member_roles or profile_role == CLIENT_MEMBER_ROLE_BROKER
    is_client_admin = CLIENT_MEMBER_ROLE_CLIENT_ADMIN in member_roles
    is_client_user = CLIENT_MEMBER_ROLE_CLIENT_USER in member_roles

    has_crm = is_platform_admin
    if crm_panorama_ids is not None and not has_crm:
        try:
            has_crm = bool(crm_panorama_ids(sb, user_id, role))
        except Exception:
            has_crm = False

    if is_platform_admin:
        portal_role = profile_role
    elif is_client_admin:
        portal_role = CLIENT_MEMBER_ROLE_CLIENT_ADMIN
    elif is_broker:
        portal_role = CLIENT_MEMBER_ROLE_BROKER
    elif is_client_user:
        portal_role = CLIENT_MEMBER_ROLE_CLIENT_USER
    else:
        portal_role = profile_role

    portal_only = (is_broker and not is_platform_admin) or is_client_admin
    # Signed-up users outside any client group create one or ask to join one (/onboarding) first.
    needs_onboarding = not (is_platform_admin or is_broker or teams) and not _has_direct_access(sb, user_id)
    first_team = teams[0] if teams else {}
    identity = {
        'user_id': str(profile.get('user_id') or user_id),
        'role': profile_role,
        'portal_role': portal_role,
        'org_id': str(profile.get('org_id')) if profile.get('org_id') else None,
        'org': _load_org(sb, profile.get('org_id')),
        'display_name': profile.get('display_name') or profile.get('email') or '',
        'email': profile.get('email') or '',
        'is_admin': is_platform_admin,
        'is_broker': is_broker,
        'is_client_admin': is_client_admin,
        'is_client_user': is_client_user,
        'is_client_member': bool(teams),
        'has_crm_access': has_crm,
        'can_manage_team': bool(is_client_admin and not is_broker),
        'can_manage_deals': bool(is_platform_admin or is_client_admin or is_client_user),
        'client_group_id': first_team.get('id', ''),
        'client_group_name': first_team.get('name', ''),
        'client_group_names': [t['name'] for t in teams if t['name']],
        'needs_onboarding': needs_onboarding,
        'home_path': (
            '/projectselection' if is_platform_admin and not portal_only
            else '/onboarding' if needs_onboarding
            else '/customer-dashboard'
        ),
    }
    _store(key, identity)
    return dict(identity)
