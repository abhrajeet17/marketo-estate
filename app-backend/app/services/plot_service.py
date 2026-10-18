"""
Plot: fetch list, create, update, delete, label position. Optional S3 delete in delete_plot.
"""
import json
from datetime import datetime

from app.services.storage_service import delete_plot_from_s3

_FIELDS_BASE = 'id, panorama_id, name, area, price, status, description, color, media_photo, media_video, points, created_at, updated_at, image_filename'
_FIELDS_LINKS = _FIELDS_BASE.replace('image_filename', 'linked_panorama_id, image_filename')
_FIELDS_LABEL = _FIELDS_LINKS + ', label_longitude, label_latitude'


def _normalize_plot_row(row):
    p = dict(row)
    if isinstance(p.get('points'), str):
        try:
            p['points'] = json.loads(p['points'])
        except Exception:
            p['points'] = []
    p['has_image'] = bool(p.get('image_filename'))
    p.pop('image_filename', None)
    if p.get('label_longitude') is not None:
        try:
            p['label_longitude'] = float(p['label_longitude'])
        except (TypeError, ValueError):
            p['label_longitude'] = None
    if p.get('label_latitude') is not None:
        try:
            p['label_latitude'] = float(p['label_latitude'])
        except (TypeError, ValueError):
            p['label_latitude'] = None
    return p


def fetch_plots(sb, panorama_id):
    """Return list of plot dicts for panorama. Tries label columns, then links, then base."""
    try:
        r = sb.table('plots').select(_FIELDS_LABEL).eq('panorama_id', panorama_id).order('created_at').execute()
    except Exception:
        try:
            r = sb.table('plots').select(_FIELDS_LABEL.replace(', label_longitude, label_latitude', '')).eq('panorama_id', panorama_id).order('created_at').execute()
        except Exception as e2:
            if 'linked_panorama_id' in str(e2).lower():
                r = sb.table('plots').select(_FIELDS_BASE).eq('panorama_id', panorama_id).order('created_at').execute()
            else:
                raise
    return [_normalize_plot_row(row) for row in (r.data or [])]


def create_plot(sb, panorama_id, data):
    insert_row = {
        'panorama_id': panorama_id,
        'name': data['name'],
        'area': data.get('area', ''),
        'price': data.get('price', ''),
        'status': data.get('status', 'available'),
        'description': data.get('description', ''),
        'color': data.get('color', 'emerald'),
        'media_photo': data.get('media_photo', ''),
        'media_video': data.get('media_video', ''),
        'points': data['points'],
    }
    if 'linked_panorama_id' in data:
        raw = data.get('linked_panorama_id')
        link_id = int(raw) if raw is not None and str(raw).strip() else None
        if link_id is not None:
            insert_row['linked_panorama_id'] = link_id
    try:
        r = sb.table('plots').insert(insert_row).execute()
    except Exception as e:
        if 'linked_panorama_id' in str(e).lower():
            insert_row.pop('linked_panorama_id', None)
            r = sb.table('plots').insert(insert_row).execute()
        else:
            raise
    if not r.data or len(r.data) == 0:
        raise RuntimeError('Insert failed')
    sb.table('panoramas').update({'updated_at': datetime.utcnow().isoformat()}).eq('id', panorama_id).execute()
    return r.data[0]['id']


def get_plot_panorama_id(sb, plot_id):
    pl = sb.table('plots').select('panorama_id').eq('id', plot_id).limit(1).execute()
    if not pl.data or len(pl.data) == 0:
        return None
    return pl.data[0].get('panorama_id')


def delete_plot(sb, plot_id, delete_s3_filename=None):
    row = sb.table('plots').select('panorama_id, image_filename').eq('id', plot_id).limit(1).execute()
    if not row.data or len(row.data) == 0:
        return None
    panorama_id = row.data[0]['panorama_id']
    image_filename = (row.data[0].get('image_filename') or '').strip()
    sb.table('plots').delete().eq('id', plot_id).execute()
    if delete_s3_filename or image_filename:
        delete_plot_from_s3(delete_s3_filename or image_filename)
    sb.table('panoramas').update({'updated_at': datetime.utcnow().isoformat()}).eq('id', panorama_id).execute()
    return panorama_id


def update_plot(sb, plot_id, data):
    pl = sb.table('plots').select('panorama_id').eq('id', plot_id).limit(1).execute()
    if not pl.data or len(pl.data) == 0:
        return None
    panorama_id = pl.data[0]['panorama_id']
    upd = {'updated_at': datetime.utcnow().isoformat()}
    for key in ('name', 'area', 'price', 'status', 'description', 'color', 'media_photo', 'media_video', 'points'):
        if key in data:
            upd[key] = data.get(key)
    if 'linked_panorama_id' in data:
        raw = data.get('linked_panorama_id')
        upd['linked_panorama_id'] = int(raw) if raw is not None and str(raw).strip() else None
    if 'label_longitude' in data:
        try:
            v = data.get('label_longitude')
            upd['label_longitude'] = float(v) if v is not None else None
        except (TypeError, ValueError):
            upd['label_longitude'] = None
    if 'label_latitude' in data:
        try:
            v = data.get('label_latitude')
            upd['label_latitude'] = float(v) if v is not None else None
        except (TypeError, ValueError):
            upd['label_latitude'] = None
    try:
        sb.table('plots').update(upd).eq('id', plot_id).execute()
    except Exception as e:
        for key in ('linked_panorama_id', 'label_longitude', 'label_latitude'):
            if key in str(e).lower() and key in upd:
                upd.pop(key, None)
        sb.table('plots').update(upd).eq('id', plot_id).execute()
    sb.table('panoramas').update({'updated_at': datetime.utcnow().isoformat()}).eq('id', panorama_id).execute()
    return panorama_id


def update_plot_label_position(sb, plot_id, lon_f, lat_f):
    pl = sb.table('plots').select('panorama_id').eq('id', plot_id).limit(1).execute()
    if not pl.data or len(pl.data) == 0:
        return None
    panorama_id = pl.data[0]['panorama_id']
    upd = {'updated_at': datetime.utcnow().isoformat()}
    if lon_f is not None:
        upd['label_longitude'] = lon_f
    if lat_f is not None:
        upd['label_latitude'] = lat_f
    sb.table('plots').update(upd).eq('id', plot_id).execute()
    sb.table('panoramas').update({'updated_at': datetime.utcnow().isoformat()}).eq('id', panorama_id).execute()
    return panorama_id
