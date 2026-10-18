"""
Org: get org/me, org name/slug for panorama, slugify. Theme from cookie is request-bound (controller).
"""
import re


def slugify_org_name(name):
    value = str(name or '').strip().lower()
    if not value:
        return 'org'
    value = re.sub(r'[^a-z0-9]+', '-', value)
    value = re.sub(r'-{2,}', '-', value).strip('-')
    return value or 'org'


def get_org_name_and_slug_for_panorama(sb, panorama):
    org_name = None
    org_id = (panorama or {}).get('org_id') if isinstance(panorama, dict) else None
    if sb and org_id:
        try:
            r = sb.table('organizations').select('name').eq('id', org_id).limit(1).execute()
            if r.data and len(r.data) > 0:
                org_name = r.data[0].get('name')
        except Exception:
            org_name = None
    org_name = str(org_name or 'MarketoState')
    return org_name, slugify_org_name(org_name)


def get_org_me(sb, user_id):
    """Return (profile_dict, org_dict or None). Org has slug."""
    from app.core.auth import get_profile
    profile = get_profile(sb, user_id) or {}
    org_id = profile.get('org_id')
    org = None
    if org_id:
        try:
            r = sb.table('organizations').select('id, name, accent_color, created_at, updated_at').eq('id', org_id).limit(1).execute()
            if r.data and len(r.data) > 0:
                org = dict(r.data[0])
                for k in ('created_at', 'updated_at'):
                    if k in org and org[k]:
                        org[k] = str(org[k])
                org['slug'] = slugify_org_name(org.get('name'))
        except Exception:
            pass
    return profile, org


def normalize_hex(hex_str):
    v = str(hex_str or '').strip()
    if not v:
        return None
    if v[0] != '#':
        v = '#' + v
    if len(v) == 4:
        v = '#' + v[1] * 2 + v[2] * 2 + v[3] * 2
    if not re.match(r'^#[0-9a-fA-F]{6}$', v):
        return None
    return v.lower()


def lighten_hex(hex_str, amount):
    try:
        n = int((hex_str or '#c9a962').lstrip('#')[:6], 16)
        r, g, b = (n >> 16) & 255, (n >> 8) & 255, n & 255
        a = max(0, min(1, float(amount)))
        r = min(255, round(r + (255 - r) * a))
        g = min(255, round(g + (255 - g) * a))
        b = min(255, round(b + (255 - b) * a))
        return '#{:02x}{:02x}{:02x}'.format(r, g, b)
    except Exception:
        return hex_str or '#c9a962'


def get_org_theme_from_accent(accent_hex):
    """Build theme dict from accent hex (e.g. from cookie)."""
    accent = normalize_hex(accent_hex)
    if not accent:
        return None
    r, g, b = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
    return {
        'accent': accent,
        'accent_hover': lighten_hex(accent, 0.08),
        'accent_2': lighten_hex(accent, 0.18),
        'accent_dim': 'rgba({}, {}, {}, 0.3)'.format(r, g, b),
        'accent_muted': 'rgba({}, {}, {}, 0.15)'.format(r, g, b),
        'accent_soft': 'rgba({}, {}, {}, 0.08)'.format(r, g, b),
    }
