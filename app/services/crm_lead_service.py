"""
Unified CRM lead domain logic.

One table (public.crm_leads) holds every CRM record. `record_status` is either
'interest' or 'deal'. The Contacts tab is simply "every deal".

Controllers stay thin: scoping, shaping, validation and the permission rules
for interest/deal records live here.
"""
import json
import re
import time
from datetime import datetime

from app.services.access_policy import _chunks, get_client_memberships
from app.services.uam_reference_service import (
    BROKER_REFERRED_CONTACT_FIELDS,
    CLIENT_MEMBER_REFERENCE_ROLE_LABELS,
    CLIENT_MEMBER_ROLE_BROKER,
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    _interest_contact_is_revealed,
    _interest_has_broker_reference,
    _normalize_client_member_role,
    apply_broker_referred_contact_mask,
    can_user_reveal_broker_referred_contact,
)

LEAD_TABLE = 'crm_leads'
STATUS_INTEREST = 'interest'
STATUS_DEAL = 'deal'
LEAD_STATUSES = (STATUS_INTEREST, STATUS_DEAL)

DEAL_STAGES = ('new', 'contacted', 'site_visit', 'negotiation', 'won', 'lost')
DEAL_STAGE_LABELS = {
    'new': 'New',
    'contacted': 'Contacted',
    'site_visit': 'Site Visit',
    'negotiation': 'Negotiation',
    'won': 'Won',
    'lost': 'Lost',
}
CLOSED_DEAL_STAGES = ('won', 'lost')

LEAD_SELECT_COLUMNS = (
    'id, record_status, org_id, client_id, panorama_id, submitted_by, reference_user_id, '
    'reference_user_role, contact_revealed_at, assigned_to, assigned_at, customer_name, '
    'customer_email, customer_phone, customer_birthday, customer_address, customer_street, '
    'customer_city, customer_state, customer_country, customer_zip_code, title, description, '
    'category, lead_source, lead_category, lead_status, campaign_type, campaign_status, plots, '
    'notes, custom_fields, deal_title, deal_stage, deal_amount, deal_currency, deal_is_active, '
    'deal_project_name, converted_at, converted_by, created_at, updated_at'
)

LEAD_SORT_FIELDS = (
    'created_at', 'updated_at', 'customer_name', 'customer_email', 'customer_phone', 'category',
    'lead_source', 'deal_title', 'deal_stage', 'deal_project_name', 'converted_at', 'customer_birthday',
)
# Contact columns are blanked for viewers who may not see them; ordering by them
# would leak the hidden ordering, so they are never sortable for those viewers.
LEAD_SORT_FIELDS_MASKED = tuple(f for f in LEAD_SORT_FIELDS if f not in ('customer_email', 'customer_phone'))

# Text field caps (chars). Anything longer is rejected at the boundary so a
# create can never store a value the edit form cannot round-trip.
FIELD_CAPS = {
    'customer_name': 100,
    'customer_email': 254,
    'customer_phone': 40,
    'title': 40,
    'category': 100,
    'customer_street': 100,
    'customer_city': 100,
    'customer_state': 100,
    'customer_country': 100,
    'customer_zip_code': 40,
    'customer_address': 500,
    'description': 500,
    'lead_source': 100,
    'lead_category': 100,
    'lead_status': 100,
    'campaign_type': 100,
    'campaign_status': 100,
    'notes': 4000,
    'deal_title': 200,
    'deal_amount': 60,
    'deal_currency': 8,
    'deal_project_name': 200,
}
FIELD_LABELS = {
    'customer_name': 'Name',
    'customer_email': 'Email',
    'customer_phone': 'Phone',
    'title': 'Title',
    'category': 'Category',
    'customer_street': 'Street',
    'customer_city': 'City',
    'customer_state': 'State',
    'customer_country': 'Country',
    'customer_zip_code': 'Zip code',
    'customer_address': 'Address',
    'description': 'Description',
    'lead_source': 'Lead source',
    'lead_category': 'Lead category',
    'lead_status': 'Lead status',
    'campaign_type': 'Campaign type',
    'campaign_status': 'Campaign status',
    'notes': 'Notes',
    'deal_title': 'Deal name',
    'deal_amount': 'Amount',
    'deal_currency': 'Currency',
    'deal_project_name': 'Project name',
    'customer_birthday': 'Birthday',
    'deal_stage': 'Stage',
}
EDITABLE_TEXT_FIELDS = tuple(FIELD_CAPS.keys())
# Columns declared NOT NULL DEFAULT '' - never write NULL into these.
NOT_NULL_TEXT_FIELDS = (
    'customer_name', 'customer_email', 'customer_phone', 'category', 'notes',
    'deal_title', 'deal_amount', 'deal_currency', 'deal_project_name',
)
# Category is optional: the customer checkout no longer asks for it.
CORE_REQUIRED_FIELDS = ('customer_name', 'customer_email', 'customer_phone')
DEAL_ONLY_FIELDS = ('deal_title', 'deal_amount', 'deal_currency', 'deal_project_name')
ADDRESS_PART_FIELDS = ('customer_street', 'customer_city', 'customer_state', 'customer_country', 'customer_zip_code')
CONTACT_FIELDS = tuple(BROKER_REFERRED_CONTACT_FIELDS) + ('customer_birthday',)

# Keys that are real columns / handled explicitly; anything else in a request
# body is swept into custom_fields.
KNOWN_REQUEST_KEYS = set(EDITABLE_TEXT_FIELDS) | {
    'customer_birthday', 'deal_stage', 'reference_user_id', 'assigned_to', 'plots', 'custom_fields',
    'panorama_id', 'client_id', 'items', 'normal_plot_ids', 'normal_project_id', 'origin', 'name', 'email',
    'phone', 'birthday', 'street', 'city', 'state', 'country', 'zip_code', 'address',
    'add_plot_ids', 'remove_plot_keys', 'record_status', 'id',
}

CUSTOM_FIELDS_MAX_KEYS = 50
CUSTOM_FIELDS_MAX_KEY_LEN = 64
CUSTOM_FIELDS_MAX_VALUE_LEN = 2000

MASK_LABEL = 'Hidden until broker reveals'


class ValidationError(Exception):
    """Boundary validation failure; `field` lets the UI highlight the input."""

    def __init__(self, message, field=None, status=400):
        super().__init__(message)
        self.message = message
        self.field = field
        self.status = status

    def payload(self):
        out = {'error': self.message}
        if self.field:
            out['field'] = self.field
        return out


# ---------------------------------------------------------------------------
# Small module cache (TTL) for lookups that repeat on every request
# ---------------------------------------------------------------------------
_CACHE = {}
_CACHE_MAX = 512


def _cache_get(key, ttl_seconds):
    row = _CACHE.get(key)
    if not row:
        return None
    if (time.time() - row[0]) > ttl_seconds:
        _CACHE.pop(key, None)
        return None
    return row[1]


def _cache_set(key, value):
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = (time.time(), value)


def invalidate_caches():
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------
def normalize_email(value):
    return str(value or '').strip().lower()


def normalize_phone(value):
    return re.sub(r'[^0-9]+', '', str(value or ''))


def safe_json(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            return fallback
    return fallback


def is_truthy(value):
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'y', 'on')


def to_iso(value):
    if value is None or value == '':
        return None
    return str(value)


def now_iso():
    return datetime.utcnow().isoformat()


def normalize_deal_stage(value):
    """Accept a stage slug or its label ('Site Visit') and return the slug or None."""
    raw = str(value or '').strip().lower()
    if not raw:
        return None
    raw = raw.replace('-', '_').replace(' ', '_')
    if raw in DEAL_STAGES:
        return raw
    for key, label in DEAL_STAGE_LABELS.items():
        if raw == label.lower().replace(' ', '_'):
            return key
    return None


def deal_is_active_for_stage(stage):
    return str(stage or '').strip().lower() not in CLOSED_DEAL_STAGES


def normalize_currency(value):
    code = re.sub(r'[^A-Za-z]', '', str(value or ''))[:8].upper()
    return code or 'INR'


def clean_text(value, key):
    text = str(value if value is not None else '').strip()
    cap = FIELD_CAPS.get(key)
    if cap and len(text) > cap:
        raise ValidationError(f"{FIELD_LABELS.get(key, key)} must be {cap} characters or less", key)
    return text


def validate_email(value, field='customer_email'):
    email = str(value or '').strip()
    if not email or '@' not in email or ' ' in email or email.startswith('@') or email.endswith('@'):
        raise ValidationError('Valid email is required', field)
    return email


def birthday_value(raw, field='customer_birthday'):
    """Nullable `date` column: '' -> None, otherwise strict YYYY-MM-DD."""
    text = str(raw if raw is not None else '').strip()
    if not text:
        return None
    text = text[:10]
    try:
        return datetime.strptime(text, '%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:
        raise ValidationError('Birthday must be in YYYY-MM-DD format', field)


def compose_address(parts):
    return ', '.join([str(p or '').strip() for p in parts if str(p or '').strip()])


def _clean_custom_value(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:CUSTOM_FIELDS_MAX_VALUE_LEN]
    try:
        encoded = json.dumps(value)
    except Exception:
        return None
    if len(encoded) > CUSTOM_FIELDS_MAX_VALUE_LEN:
        return None
    return value


def extract_custom_fields(data, known_keys=None):
    """Explicit `custom_fields` plus every unrecognised key, bounded."""
    payload = {}
    data = data if isinstance(data, dict) else {}
    if isinstance(data.get('custom_fields'), dict):
        for k, v in data.get('custom_fields').items():
            key = str(k or '').strip()[:CUSTOM_FIELDS_MAX_KEY_LEN]
            if key:
                payload[key] = _clean_custom_value(v)
    known = set(KNOWN_REQUEST_KEYS)
    for k in (known_keys or []):
        known.add(str(k or '').strip())
    for k, v in data.items():
        key = str(k or '').strip()
        if not key or key in known or key == 'custom_fields':
            continue
        payload[key[:CUSTOM_FIELDS_MAX_KEY_LEN]] = _clean_custom_value(v)
    if len(payload) > CUSTOM_FIELDS_MAX_KEYS:
        payload = dict(list(payload.items())[:CUSTOM_FIELDS_MAX_KEYS])
    return payload


def role_label(role):
    key = _normalize_client_member_role(role)
    if not key:
        return ''
    return CLIENT_MEMBER_REFERENCE_ROLE_LABELS.get(key, key.replace('_', ' ').title())


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------
def plot_identity(plot):
    """Stable identity for a plot snapshot: normal id, then plot id, then name."""
    if not isinstance(plot, dict):
        return ''
    if plot.get('normal_plot_id') is not None and str(plot.get('normal_plot_id')).strip():
        return 'normal:' + str(plot.get('normal_plot_id')).strip()
    raw = plot.get('plot_id') if plot.get('plot_id') is not None else plot.get('id')
    if raw is not None and str(raw).strip():
        return 'id:' + str(raw).strip()
    name = re.sub(r'\s+', ' ', str(plot.get('name') or '').strip()).lower()
    return ('name:' + name) if name else ''


def clean_plot_list(raw):
    """Normalise a client-sent plots array; never store arbitrary shapes."""
    plots = safe_json(raw, [])
    out = []
    if not isinstance(plots, list):
        return out
    for p in plots:
        if not isinstance(p, dict):
            continue
        pid_raw = p.get('plot_id') if p.get('plot_id') is not None else p.get('id')
        try:
            pid = int(str(pid_raw).strip()) if pid_raw is not None and str(pid_raw).strip() != '' else None
        except Exception:
            pid = None
        item = {
            'plot_id': pid,
            'id': pid,
            'name': str(p.get('name') or '').strip()[:120],
            'area': str(p.get('area') or '').strip()[:60],
            'price': str(p.get('price') or '').strip()[:60],
            'status': (str(p.get('status') or 'available').strip().lower()[:30] or 'available'),
        }
        if p.get('panorama_id') is not None:
            try:
                item['panorama_id'] = int(p.get('panorama_id'))
            except Exception:
                pass
        for key in ('normal_plot_id', 'normal_project_id', 'normal_project_name'):
            if p.get(key) not in (None, ''):
                item[key] = p.get(key)
        if item['plot_id'] is None and not item['name'] and not item.get('normal_plot_id'):
            continue
        out.append(item)
    return out


def merge_plots(existing, additions):
    """Union by identity, keeping the existing order first."""
    seen = set()
    out = []
    for p in list(existing or []) + list(additions or []):
        key = plot_identity(p)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def remove_plots(existing, remove_keys):
    keys = {str(k or '').strip() for k in (remove_keys or []) if str(k or '').strip()}
    if not keys:
        return list(existing or [])
    out = []
    for p in (existing or []):
        ident = plot_identity(p)
        pid = str(p.get('plot_id') if p.get('plot_id') is not None else (p.get('id') or '')).strip()
        if ident in keys or (pid and pid in keys) or (pid and ('id:' + pid) in keys):
            continue
        out.append(p)
    return out


def coerce_plot_ids(items):
    ids = []
    for item in (items or []):
        raw = None
        if isinstance(item, (int, float, str)):
            raw = item
        elif isinstance(item, dict):
            raw = item.get('plot_id') if 'plot_id' in item else item.get('id')
        if raw is None or str(raw).strip() == '':
            continue
        try:
            ids.append(int(raw))
        except Exception:
            continue
    return list(dict.fromkeys(ids))


def workspace_panorama_ids(sb, panorama):
    """Every panorama in the same project as `panorama` (plots can come from any of them)."""
    out = set()
    try:
        out.add(int((panorama or {}).get('id')))
    except Exception:
        pass
    ws_id = (panorama or {}).get('workspace_id')
    if ws_id:
        try:
            rows = sb.table('panoramas').select('id').eq('workspace_id', ws_id).execute().data or []
            for row in rows:
                if row.get('id') is not None:
                    out.add(int(row.get('id')))
        except Exception:
            pass
    return sorted(out)


def build_plot_snapshot(sb, panorama, plot_ids):
    """Snapshot rows from public.plots for plots inside the lead's project only."""
    if not plot_ids:
        return []
    allowed = workspace_panorama_ids(sb, panorama)
    if not allowed:
        return []
    found = {}
    for chunk in _chunks(plot_ids, 200):
        rows = (
            sb.table('plots')
            .select('id, panorama_id, name, area, price, status')
            .in_('id', chunk)
            .in_('panorama_id', allowed)
            .execute()
            .data or []
        )
        for row in rows:
            if row and row.get('id') is not None:
                found[int(row.get('id'))] = row
    snapshot = []
    for pid in plot_ids:
        row = found.get(int(pid))
        if not row:
            continue
        snapshot.append({
            'plot_id': int(row.get('id')),
            'id': int(row.get('id')),
            'panorama_id': int(row.get('panorama_id')) if row.get('panorama_id') is not None else None,
            'name': row.get('name') or '',
            'area': row.get('area') or '',
            'price': row.get('price') or '',
            'status': row.get('status') or '',
        })
    return snapshot


def build_normal_plot_snapshot(sb, owner_user_id, normal_plot_ids):
    if not normal_plot_ids or not owner_user_id:
        return []
    rows = (
        sb.table('crm_normal_plots')
        .select('id, project_id, project_name, name, area, price, status')
        .eq('owner_user_id', str(owner_user_id))
        .in_('id', [int(x) for x in normal_plot_ids])
        .execute()
        .data or []
    )
    out = []
    for row in rows:
        out.append({
            'plot_id': int(row.get('id')),
            'id': int(row.get('id')),
            'normal_plot_id': int(row.get('id')),
            'normal_project_id': row.get('project_id'),
            'normal_project_name': row.get('project_name') or '',
            'name': row.get('name') or '',
            'area': row.get('area') or '',
            'price': row.get('price') or '',
            'status': row.get('status') or '',
        })
    return out


def deal_amount_from_plots(plots):
    """Sum numeric plot prices; fall back to the first price text."""
    prices = [str((p or {}).get('price') or '').strip() for p in (plots or []) if isinstance(p, dict)]
    prices = [x for x in prices if x]
    if not prices:
        return ''
    total = 0.0
    numeric = True
    for text in prices:
        cleaned = re.sub(r'[^0-9.\-]', '', text)
        if not cleaned or cleaned in ('-', '.'):
            numeric = False
            break
        try:
            total += float(cleaned)
        except ValueError:
            numeric = False
            break
    if numeric and len(prices) > 1:
        if total == int(total):
            return f"{int(total):,}"
        return f"{total:,.2f}"
    return prices[0] if len(prices) == 1 else (prices[0] + ' + more')


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def panorama_info_map(sb, panorama_ids):
    """{pid: {org_id, name, workspace_id, workspace_name}} for a set of panoramas."""
    ids = []
    seen = set()
    for pid in panorama_ids or []:
        try:
            p_int = int(pid)
        except Exception:
            continue
        if p_int not in seen:
            seen.add(p_int)
            ids.append(p_int)
    if not ids:
        return {}
    cache_key = ('pano_info', tuple(sorted(ids)))
    cached = _cache_get(cache_key, 15)
    if cached is not None:
        return dict(cached)
    out = {}
    ws_ids = set()
    for chunk in _chunks(ids, 200):
        try:
            rows = sb.table('panoramas').select('id, org_id, name, workspace_id').in_('id', chunk).execute().data or []
        except Exception:
            rows = []
        for row in rows:
            try:
                pid = int(row.get('id'))
            except Exception:
                continue
            wsid = row.get('workspace_id')
            out[pid] = {
                'org_id': row.get('org_id'),
                'name': str(row.get('name') or f'Panorama #{pid}'),
                'workspace_id': str(wsid) if wsid else None,
                'workspace_name': '',
            }
            if wsid:
                ws_ids.add(str(wsid))
    if ws_ids:
        names = {}
        for chunk in _chunks(list(ws_ids), 100):
            try:
                rows = sb.table('workspaces').select('id, name').in_('id', chunk).execute().data or []
            except Exception:
                rows = []
            for row in rows:
                names[str(row.get('id'))] = str(row.get('name') or '')
        for info in out.values():
            if info.get('workspace_id'):
                info['workspace_name'] = names.get(info['workspace_id'], '')
    _cache_set(cache_key, out)
    return dict(out)


def client_name_map(sb, client_ids):
    ids = sorted({str(c) for c in (client_ids or []) if c})
    if not ids:
        return {}
    cache_key = ('client_names', tuple(ids))
    cached = _cache_get(cache_key, 30)
    if cached is not None:
        return dict(cached)
    out = {}
    for chunk in _chunks(ids, 200):
        try:
            rows = sb.table('clients').select('id, name').in_('id', chunk).execute().data or []
        except Exception:
            rows = []
        for row in rows:
            cid = str(row.get('id') or '')
            if cid:
                out[cid] = str(row.get('name') or '').strip() or cid
    _cache_set(cache_key, out)
    return dict(out)


def profile_name_map(sb, user_ids):
    ids = sorted({str(u) for u in (user_ids or []) if u})
    if not ids:
        return {}
    cache_key = ('profile_names', tuple(ids))
    cached = _cache_get(cache_key, 30)
    if cached is not None:
        return dict(cached)
    out = {}
    for chunk in _chunks(ids, 100):
        try:
            rows = sb.table('profiles').select('user_id, display_name, email').in_('user_id', chunk).execute().data or []
        except Exception:
            rows = []
        for row in rows:
            uid = str(row.get('user_id') or '')
            if uid:
                out[uid] = str(row.get('display_name') or row.get('email') or '').strip()
    _cache_set(cache_key, out)
    return dict(out)


def resolve_reference_user_role(sb, reference_user_id, client_id=None):
    """Member role of the reference user, preferring the lead's own client group."""
    uid = str(reference_user_id or '').strip()
    if not uid:
        return None
    cache_key = ('ref_role', uid, str(client_id or ''))
    cached = _cache_get(cache_key, 30)
    if cached is not None:
        return cached or None
    memberships = get_client_memberships(sb, uid)
    priority = {CLIENT_MEMBER_ROLE_BROKER: 0, CLIENT_MEMBER_ROLE_CLIENT_ADMIN: 1, CLIENT_MEMBER_ROLE_CLIENT_USER: 2}
    best = None
    best_rank = None
    for member in memberships:
        role = _normalize_client_member_role(member.get('member_role'))
        if role not in priority:
            continue
        in_client = bool(client_id) and str(member.get('client_id') or '') == str(client_id)
        rank = (0 if in_client else 1, priority[role])
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = role
    if not best:
        # Platform-level broker profiles without a membership row
        try:
            prof = sb.table('profiles').select('role').eq('user_id', uid).limit(1).execute().data or []
            if prof and str((prof[0] or {}).get('role') or '').strip().lower() == 'broker':
                best = CLIENT_MEMBER_ROLE_BROKER
        except Exception:
            pass
    _cache_set(cache_key, best or '')
    return best


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------
def is_platform_admin_role(role):
    return str(role or '').strip().lower() in ('admin', 'superadmin')


def get_user_caps(sb, user_id, role):
    """What this user may do with CRM records (independent of row scope)."""
    cache_key = ('caps', str(user_id), str(role or ''))
    cached = _cache_get(cache_key, 8)
    if cached is not None:
        return dict(cached)
    platform_admin = is_platform_admin_role(role)
    memberships = get_client_memberships(sb, user_id) if not platform_admin else []
    roles = {_normalize_client_member_role(m.get('member_role')) for m in memberships}
    is_client_admin = CLIENT_MEMBER_ROLE_CLIENT_ADMIN in roles
    is_client_user = CLIENT_MEMBER_ROLE_CLIENT_USER in roles
    is_broker = CLIENT_MEMBER_ROLE_BROKER in roles or str(role or '').strip().lower() == 'broker'
    caps = {
        'is_platform_admin': platform_admin,
        'is_client_admin': is_client_admin,
        'is_client_user': is_client_user,
        'is_broker': is_broker,
        'broker_only': bool(is_broker and not (platform_admin or is_client_admin or is_client_user)),
        # Brokers may never convert or edit deals; client staff and platform admins may.
        'can_manage_deals': bool(platform_admin or is_client_admin or is_client_user),
    }
    _cache_set(cache_key, caps)
    return dict(caps)


# ---------------------------------------------------------------------------
# Query scoping
# ---------------------------------------------------------------------------
def apply_client_scope(query, client_scope_ids, requested_client_id=None):
    if requested_client_id:
        return query.eq('client_id', str(requested_client_id))
    if client_scope_ids is not None:
        return query.in_('client_id', list(client_scope_ids))
    return query


def apply_broker_visibility(query, broker_user_id):
    """Brokers only see records they referred or submitted."""
    uid = str(broker_user_id or '').strip()
    if not uid:
        return query
    return query.or_(f"reference_user_id.eq.{uid},submitted_by.eq.{uid}")


def apply_record_scope(query, scope, *, requested_client_id=None):
    query = query.in_('panorama_id', list(scope['panorama_ids']))
    query = apply_client_scope(query, scope.get('client_scope_ids'), requested_client_id)
    if scope.get('reference_scope_user_id'):
        query = apply_broker_visibility(query, scope['reference_scope_user_id'])
    return query


def get_lead_for_user(sb, lead_id, scope):
    """One lead by id, or None when it is outside the caller's scope."""
    if not scope or not scope.get('panorama_ids'):
        return None
    try:
        query = sb.table(LEAD_TABLE).select(LEAD_SELECT_COLUMNS).eq('id', str(lead_id))
        query = apply_record_scope(query, scope)
        rows = query.limit(1).execute().data or []
        return rows[0] if rows else None
    except Exception:
        return None


def scoped_update(sb, lead_id, upd, scope):
    """UPDATE guarded by the same scope filters as the read, so a row cannot
    slip out of scope between the check and the write."""
    query = sb.table(LEAD_TABLE).update(upd).eq('id', str(lead_id))
    query = apply_record_scope(query, scope)
    return query.execute().data or []


def scoped_delete(sb, lead_id, scope):
    query = sb.table(LEAD_TABLE).delete().eq('id', str(lead_id))
    query = apply_record_scope(query, scope)
    return query.execute().data or []


# ---------------------------------------------------------------------------
# Row shaping (API representation + permission flags)
# ---------------------------------------------------------------------------
def contact_requires_reveal(row):
    return _interest_has_broker_reference(row) and not _interest_contact_is_revealed(row)


def convert_block_reason(row, user_id, caps):
    """'' when the caller may convert this interest, else a human reason."""
    if str((row or {}).get('record_status') or '') == STATUS_DEAL:
        return 'This record is already a deal'
    if not caps.get('can_manage_deals'):
        return 'Only client admins and client users can convert interests to deals'
    if contact_requires_reveal(row) and str(row.get('reference_user_id') or '') != str(user_id or ''):
        return 'The referring broker must reveal the contact before this interest can be converted'
    return ''


def shape_lead_rows(sb, rows, *, user_id, role, reference_scope_user_id, caps, panorama_map=None):
    rows = list(rows or [])
    if not rows:
        return []
    pano_ids = [r.get('panorama_id') for r in rows if r.get('panorama_id') is not None]
    pmap = panorama_map if panorama_map is not None else panorama_info_map(sb, pano_ids)
    cnames = client_name_map(sb, [r.get('client_id') for r in rows if r.get('client_id')])
    ref_ids = [r.get('reference_user_id') for r in rows if r.get('reference_user_id')]
    pnames = profile_name_map(sb, ref_ids)
    out = []
    for raw in rows:
        item = apply_broker_referred_contact_mask(
            raw, user_id=user_id, role=role, reference_scope_user_id=reference_scope_user_id, sb=sb,
        )
        try:
            pid = int(item.get('panorama_id'))
        except Exception:
            pid = None
        pinfo = pmap.get(pid) or {}
        is_deal = str(item.get('record_status') or STATUS_INTEREST) == STATUS_DEAL
        ref_uid = str(item.get('reference_user_id') or '').strip()
        ref_role = _normalize_client_member_role(item.get('reference_user_role'))
        for key in ('created_at', 'updated_at', 'contacted_at', 'converted_at', 'assigned_at', 'contact_revealed_at'):
            if item.get(key):
                item[key] = str(item[key])
        for key in ('submitted_by', 'reference_user_id', 'assigned_to', 'converted_by', 'client_id', 'org_id'):
            if item.get(key):
                item[key] = str(item[key])
        if item.get('customer_birthday'):
            item['customer_birthday'] = str(item['customer_birthday'])[:10]
        plots = item.get('plots')
        item['plots'] = plots if isinstance(plots, list) else []
        custom = item.get('custom_fields')
        item['custom_fields'] = custom if isinstance(custom, dict) else {}
        item['is_deal'] = is_deal
        item['panorama_name'] = pinfo.get('name') or (f'Project #{pid}' if pid else '')
        item['workspace_id'] = pinfo.get('workspace_id')
        item['workspace_name'] = pinfo.get('workspace_name') or ''
        item['project_label'] = item['workspace_name'] or item['panorama_name']
        item['client_name'] = cnames.get(str(item.get('client_id') or ''), '')
        item['reference_user_name'] = pnames.get(ref_uid, '') if ref_uid else ''
        item['reference_user_role'] = ref_role or ''
        item['reference_user_role_label'] = role_label(ref_role) if ref_uid else ''
        item['is_self_reference'] = bool(ref_uid and ref_uid == str(user_id or ''))
        item['deal_stage'] = str(item.get('deal_stage') or 'new')
        item['deal_stage_label'] = DEAL_STAGE_LABELS.get(item['deal_stage'], item['deal_stage'].replace('_', ' ').title())
        item['plot_count'] = len(item['plots'])
        item['contact_hidden_label'] = MASK_LABEL if item.get('contact_hidden') else ''
        item['can_reveal_contact'] = bool(can_user_reveal_broker_referred_contact(user_id, raw))
        item['can_edit'] = bool(caps.get('can_manage_deals')) if is_deal else True
        item['can_edit_contact'] = bool(item['can_edit'] and not item.get('contact_hidden'))
        reason = convert_block_reason(raw, user_id, caps)
        item['can_convert'] = (not is_deal) and (reason == '')
        item['convert_blocked_reason'] = reason if not is_deal else ''
        item['can_delete'] = bool(caps.get('can_manage_deals')) if is_deal else True
        item['can_move_stage'] = bool(is_deal and caps.get('can_manage_deals'))
        out.append(item)
    return out


def shape_lead_row(sb, row, **kwargs):
    shaped = shape_lead_rows(sb, [row], **kwargs)
    return shaped[0] if shaped else None


# ---------------------------------------------------------------------------
# Request parsing shared by create/update
# ---------------------------------------------------------------------------
def parse_customer_fields(data, *, require_core):
    """Pull the customer/lead text columns out of a request body.

    Returns {column: value}. With require_core=True the four compulsory fields
    must be present and non-empty (create). Aliases used by the public form
    (name/email/phone/...) are accepted.
    """
    aliases = {
        'customer_name': ('customer_name', 'name'),
        'customer_email': ('customer_email', 'email'),
        'customer_phone': ('customer_phone', 'phone'),
        'customer_street': ('customer_street', 'street'),
        'customer_city': ('customer_city', 'city'),
        'customer_state': ('customer_state', 'state'),
        'customer_country': ('customer_country', 'country'),
        'customer_zip_code': ('customer_zip_code', 'zip_code'),
        'customer_address': ('customer_address', 'address'),
    }
    out = {}
    for key in EDITABLE_TEXT_FIELDS:
        if key in DEAL_ONLY_FIELDS:
            continue
        present = False
        value = None
        for alias in aliases.get(key, (key,)):
            if alias in data:
                present = True
                value = data.get(alias)
                break
        if not present and not require_core:
            continue
        out[key] = clean_text(value, key)
    if require_core:
        for key in CORE_REQUIRED_FIELDS:
            if not out.get(key):
                raise ValidationError(f"{FIELD_LABELS[key]} is required", key)
    if out.get('customer_email'):
        out['customer_email'] = validate_email(out['customer_email'])
    if 'customer_email' in out and not out['customer_email'] and require_core:
        raise ValidationError('Valid email is required', 'customer_email')
    if 'customer_address' in out and not out['customer_address'] and require_core:
        out['customer_address'] = compose_address([out.get(k) for k in ADDRESS_PART_FIELDS])
    if require_core and not out.get('title'):
        first = str(out.get('customer_name') or '').split(' ')[0].replace('.', '').lower()
        if first in ('mr', 'mrs', 'ms', 'dr'):
            out['title'] = 'Dr' if first == 'dr' else first.capitalize()
    return out


def text_or_null(key, value):
    """Store '' for NOT NULL text columns, NULL for nullable ones."""
    if key in NOT_NULL_TEXT_FIELDS:
        return value or ''
    return value or None
