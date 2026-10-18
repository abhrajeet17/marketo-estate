"""
Building Plan: the customer-facing aerial -> tower -> floor -> unit flow built
from linked building maps, plus the Show Interest hand-off into the CRM.

Routes
  GET  /building-plan/<token>[/<path>]             customer view (deep links resolve client-side)
  GET  /api/public/building-plan/<token>           the whole linked tree in one payload
  POST /api/public/building-plan/<token>/interest  Show Interest -> crm_leads (category "Building Plan")
  GET  /api/building-maps/flow                     admin view-builder summary (maps + links)
"""
import gzip
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from flask import jsonify, make_response, render_template, request

from app.core.auth import require_admin
from app.paths import static_file_path
from app.core.database import get_supabase
from app.services import crm_lead_service as leads
from app.services.building_map_service import (
    get_building_map_by_token as bm_get_by_token,
    list_images_for_maps as bm_images_for_maps,
    list_zones_for_maps as bm_zones_for_maps,
    normalize_view_config,
    normalize_zone_meta,
    zone_link_type,
)
from app.services.crm_lead_service import ValidationError
from app.services.storage_service import get_building_map_s3_url, get_floorplan_s3_url
from app.services.uam_reference_service import (
    _normalize_client_member_role,
    _project_reference_users,
    _validate_project_reference_user,
)

BUILDING_PLAN_CATEGORY = 'Building Plan'
MAX_TREE_MAPS = 60
TREE_FRESH_SECONDS = 30
# Signed image URLs live for SUPABASE_S3_SIGNED_URL_TTL (1h); never serve a tree older than this.
TREE_MAX_STALE_SECONDS = 40 * 60

_tree_cache = {}          # token -> (built_at, tree)
_tree_refreshing = set()  # tokens with a background rebuild in flight
_tree_cache_lock = threading.Lock()


def sign_many(sign_fn, filenames, verify=True):
    """{filename: url}. Verified signing does a HEAD round-trip per object, so those run concurrently."""
    names = sorted({f for f in filenames if f})
    if not names:
        return {}
    if not verify:
        return {n: sign_fn(n, verify=False) for n in names}
    if len(names) == 1:
        return {names[0]: sign_fn(names[0])}
    with ThreadPoolExecutor(max_workers=min(16, len(names))) as pool:
        return dict(zip(names, pool.map(sign_fn, names)))


def _rebuild_tree(token):
    try:
        sb = get_supabase()
        root = bm_get_by_token(sb, token) if sb else None
        if not root:
            with _tree_cache_lock:
                _tree_cache.pop(token, None)
            return None
        tree = build_plan_tree(sb, root)
        with _tree_cache_lock:
            if len(_tree_cache) > 200:
                _tree_cache.clear()
            _tree_cache[token] = (time.time(), tree)
        return tree
    finally:
        with _tree_cache_lock:
            _tree_refreshing.discard(token)


def _refresh_in_background(token):
    with _tree_cache_lock:
        if token in _tree_refreshing:
            return
        _tree_refreshing.add(token)
    threading.Thread(target=_rebuild_tree, args=(token,), daemon=True).start()


def invalidate_building_plan_cache():
    """Builder edits: mark every cached tree stale and rebuild them right away in the
    background, so the next customer still gets an instant (and soon fresh) response."""
    with _tree_cache_lock:
        tokens = list(_tree_cache.keys())
        for t in tokens:
            built, tree = _tree_cache[t]
            _tree_cache[t] = (0, tree)
    for t in tokens:
        _refresh_in_background(t)


def _asset_version():
    """mtime-based cache buster for the view's CSS/JS."""
    v = 0
    for rel in ('css/building_plan_view.css', 'js/building_plan_view.js'):
        try:
            v = max(v, int(os.path.getmtime(static_file_path(rel))))
        except (OSError, TypeError):
            pass
    return v


def _parse_points(raw):
    if isinstance(raw, str):
        try:
            import json
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    pts = []
    for p in raw:
        try:
            pts.append([round(float(p['x']), 1), round(float(p['y']), 1)])
        except (KeyError, TypeError, ValueError):
            continue
    return pts


def _fetch_maps(sb, ids, owner_id):
    if not ids:
        return []
    rows = sb.table('building_maps').select('*').in_('id', [str(i) for i in ids]).execute().data or []
    # Never follow a link into another account's map.
    return [r for r in rows if str(r.get('user_id')) == str(owner_id)]


def _fetch_floor_plan_items(sb, ids):
    ids = [str(i) for i in ids if i]
    if not ids:
        return {}
    rows = (
        sb.table('floor_plan_items')
        .select('id, name, image_filename, image_width, image_height')
        .in_('id', ids)
        .execute()
        .data or []
    )
    return {str(r['id']): r for r in rows}


def build_plan_tree(sb, root):
    """Walk zone -> building map links from `root` and return one compact payload."""
    owner_id = root.get('user_id')
    maps = {str(root['id']): root}
    zones_by_map = {}
    frontier = [str(root['id'])]
    while frontier and len(maps) <= MAX_TREE_MAPS:
        batch = bm_zones_for_maps(sb, frontier)
        zones_by_map.update(batch)
        next_ids = []
        for zs in batch.values():
            for z in zs:
                target = str(z.get('linked_building_map_id') or '')
                if target and target not in maps and target not in next_ids:
                    next_ids.append(target)
        next_ids = next_ids[:max(0, MAX_TREE_MAPS - len(maps))]
        fetched = _fetch_maps(sb, next_ids, owner_id)
        for m in fetched:
            maps[str(m['id'])] = m
        frontier = [str(m['id']) for m in fetched]

    images_by_map = bm_images_for_maps(sb, list(maps.keys()))
    fp_items = _fetch_floor_plan_items(sb, [
        z.get('linked_floor_plan_item_id') for zs in zones_by_map.values() for z in zs
    ])

    bm_urls = sign_many(get_building_map_s3_url, [m.get('image_filename') for m in maps.values()] +
                        [img.get('image_filename') for imgs in images_by_map.values() for img in imgs], verify=False)
    fp_urls = sign_many(get_floorplan_s3_url, [fp.get('image_filename') for fp in fp_items.values()], verify=False)

    out_maps = {}
    for mid, m in maps.items():
        cfg = normalize_view_config(m.get('view_config'))
        zones_out = []
        for z in zones_by_map.get(mid, []):
            lt = zone_link_type(z)
            target = str(z.get('linked_building_map_id') or '')
            if lt == 'building_map' and target not in maps:
                lt = ''
            entry = {
                'id': z['id'],
                'name': z.get('name') or '',
                'floor': z.get('floor_number') or 0,
                'color': z.get('color') or 'green',
                'points': _parse_points(z.get('points')),
                'image_id': z.get('image_id'),
                'link': lt,
                'meta': normalize_zone_meta(z.get('meta')),
            }
            if lt == 'building_map':
                entry['target'] = target
            elif lt == 'panorama' and z.get('linked_panorama_id'):
                entry['panorama_id'] = z['linked_panorama_id']
            elif lt == 'floor_plan':
                fp = fp_items.get(str(z.get('linked_floor_plan_item_id') or ''))
                if fp:
                    entry['floor_plan'] = {
                        'id': fp['id'],
                        'name': fp.get('name') or '',
                        'url': fp_urls.get(fp.get('image_filename')),
                        'w': fp.get('image_width') or 0,
                        'h': fp.get('image_height') or 0,
                    }
                else:
                    entry['link'] = ''
            zones_out.append(entry)
        views = [{
            'id': img['id'],
            'name': img.get('name') or 'View',
            'url': bm_urls.get(img.get('image_filename')),
            'w': img.get('image_width') or 0,
            'h': img.get('image_height') or 0,
        } for img in images_by_map.get(mid, [])]
        if not views:
            views = [{
                'id': None,
                'name': m.get('name') or 'View',
                'url': bm_urls.get(m.get('image_filename')),
                'w': m.get('image_width') or 0,
                'h': m.get('image_height') or 0,
                'lqip': cfg.get('lqip') or '',
            }]
        out_maps[mid] = {
            'id': mid,
            'name': m.get('name') or 'Building',
            'level': cfg.get('level') or '',
            'views': views,
            'zones': zones_out,
        }

    root_cfg = normalize_view_config(root.get('view_config'))
    project = {'name': root.get('name') or '', 'rera': root_cfg.get('rera_number') or '', 'brand': root_cfg.get('brand_name') or ''}
    if root.get('workspace_id'):
        try:
            ws = (
                sb.table('workspaces')
                .select('name, rera_registration')
                .eq('id', str(root['workspace_id']))
                .limit(1)
                .execute()
                .data or []
            )
            if ws:
                project['name'] = ws[0].get('name') or project['name']
                project['rera'] = project['rera'] or (ws[0].get('rera_registration') or '')
        except Exception:
            pass
    project['brand'] = project['brand'] or project['name']
    return {
        'root': str(root['id']),
        'token': root.get('share_token') or '',
        'project': project,
        'vr_tour_url': root_cfg.get('vr_tour_url') or '',
        'show_interest': root_cfg.get('show_interest', True) is not False,
        'maps': out_maps,
    }


def get_plan_tree_cached(sb, token):
    """Stale-while-revalidate: fresh hits return directly, stale-but-usable hits return
    immediately and refresh in the background; only a cold or too-old cache builds inline."""
    now = time.time()
    with _tree_cache_lock:
        hit = _tree_cache.get(token)
    if hit:
        built, tree = hit
        age = now - built
        if age < TREE_FRESH_SECONDS:
            return tree
        if built and age < TREE_MAX_STALE_SECONDS:
            _refresh_in_background(token)
            return tree
        if not built:
            # Invalidated by an edit: a rebuild is already running; wait briefly for it.
            for _ in range(30):
                time.sleep(0.05)
                with _tree_cache_lock:
                    cur = _tree_cache.get(token)
                if cur and cur[0]:
                    return cur[1]
    with _tree_cache_lock:
        _tree_refreshing.add(token)
    return _rebuild_tree(token)


def _gzip_response(resp):
    """Compress HTML/JSON for clients that accept it (the tree is ~100KB raw, ~15KB gzipped)."""
    if 'gzip' not in (request.headers.get('Accept-Encoding') or '').lower():
        return resp
    data = resp.get_data()
    if len(data) < 1024:
        return resp
    resp.set_data(gzip.compress(data, compresslevel=6))
    resp.headers['Content-Encoding'] = 'gzip'
    resp.headers['Content-Length'] = str(len(resp.get_data()))
    resp.headers['Vary'] = 'Accept-Encoding'
    return resp


def _resolve_panorama(sb, root, tree):
    """CRM leads are anchored to a panorama: the project's main one, else any in the project."""
    ws_id = root.get('workspace_id')
    if ws_id:
        try:
            ws = sb.table('workspaces').select('main_panorama_id').eq('id', str(ws_id)).limit(1).execute().data or []
            if ws and ws[0].get('main_panorama_id'):
                return int(ws[0]['main_panorama_id'])
            rows = sb.table('panoramas').select('id').eq('workspace_id', str(ws_id)).order('created_at').limit(1).execute().data or []
            if rows:
                return int(rows[0]['id'])
        except Exception:
            pass
    for m in tree['maps'].values():
        for z in m['zones']:
            if z.get('panorama_id'):
                return int(z['panorama_id'])
    rows = (
        sb.table('panoramas').select('id').eq('user_id', str(root['user_id']))
        .order('created_at').limit(1).execute().data or []
    )
    return int(rows[0]['id']) if rows else None


def _path_from_via(tree, via, map_id, zone_id):
    """Follow the customer's clicked path (zone ids from the root); None unless every hop
    is a building-map link and it ends on map_id. Needed when one map is shared by many zones."""
    if not isinstance(via, list) or len(via) > 20:
        return None
    m = tree['maps'].get(tree['root'])
    path = []
    for zid in via:
        z = next((z for z in (m or {}).get('zones', []) if str(z['id']) == str(zid)), None)
        if not z or z.get('link') != 'building_map' or z.get('target') not in tree['maps']:
            return None
        path.append((m, z))
        m = tree['maps'][z['target']]
    if not m or str(m['id']) != str(map_id):
        return None
    zone = next((z for z in m['zones'] if str(z['id']) == str(zone_id)), None)
    if not zone:
        return None
    path.append((m, zone))
    return path


def _zone_path(tree, map_id, zone_id, via=None):
    """[(map, zone)] from the root down to the clicked zone, or None if it is not in the tree."""
    if via:
        walked = _path_from_via(tree, via, map_id, zone_id)
        if walked:
            return walked
    parent = {}
    for mid, m in tree['maps'].items():
        for z in m['zones']:
            if z.get('target') and z['target'] not in parent:
                parent[z['target']] = (mid, z)
    m = tree['maps'].get(str(map_id))
    if not m:
        return None
    zone = next((z for z in m['zones'] if str(z['id']) == str(zone_id)), None)
    if not zone:
        return None
    path = [(m, zone)]
    cur = str(map_id)
    seen = {cur}
    while cur in parent and cur != tree['root']:
        pmid, pz = parent[cur]
        if pmid in seen:
            break
        seen.add(pmid)
        path.insert(0, (tree['maps'][pmid], pz))
        cur = pmid
    return path


CUSTOMER_KEYS = (
    'name', 'email', 'phone', 'birthday', 'street', 'city', 'state', 'country', 'zip_code', 'description',
)


def register_building_plan_routes(app, *, crm_cache_bump):

    def _render_view(token):
        sb = get_supabase()
        if not sb:
            return 'Database not configured', 503
        tree = get_plan_tree_cached(sb, token)
        if not tree:
            return 'Not found', 404
        resp = make_response(render_template('building_plan_view.html', tree=tree, asset_v=_asset_version()))
        resp.headers['Cache-Control'] = 'no-cache'
        return _gzip_response(resp)

    @app.route('/building-plan/<token>')
    def building_plan_view(token):
        return _render_view(token)

    @app.route('/building-plan/<token>/<path:_rest>')
    def building_plan_view_deep(token, _rest):
        return _render_view(token)

    @app.route('/api/public/building-plan/<token>')
    def api_public_building_plan(token):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        tree = get_plan_tree_cached(sb, token)
        if not tree:
            return jsonify({'error': 'Not found'}), 404
        resp = jsonify(tree)
        resp.headers['Cache-Control'] = 'public, max-age=30'
        return _gzip_response(resp)

    @app.route('/api/public/building-plan/<token>/reference-users', methods=['GET'])
    def api_public_building_plan_references(token):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        root = bm_get_by_token(sb, token)
        if not root:
            return jsonify({'error': 'Not found'}), 404
        tree = get_plan_tree_cached(sb, token)
        panorama_id = _resolve_panorama(sb, root, tree) if tree else None
        if not panorama_id:
            return jsonify({'reference_users': []})
        catalog = _project_reference_users(sb, panorama_id=panorama_id)
        return jsonify({'reference_users': catalog.get('users') or []})

    @app.route('/api/public/building-plan/<token>/interest', methods=['POST'])
    def api_public_building_plan_interest(token):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        root = bm_get_by_token(sb, token)
        if not root:
            return jsonify({'error': 'Not found'}), 404
        tree = get_plan_tree_cached(sb, token)
        if not tree or not tree.get('show_interest'):
            return jsonify({'error': 'Show Interest is turned off for this project'}), 403
        data = request.get_json(silent=True) or {}
        path = _zone_path(tree, data.get('map_id'), data.get('zone_id'), data.get('path'))
        if not path:
            return jsonify({'error': 'Select a unit or floor first', 'field': 'zone_id'}), 400
        target_map, zone = path[-1]
        # The floor the customer came through may override this unit's status.
        unit_status = zone['meta'].get('status') or ''
        if len(path) >= 2:
            unit_status = (path[-2][1]['meta'].get('unit_status') or {}).get(str(zone['id'])) or unit_status
        if zone['meta'].get('hide_interest') or unit_status == 'sold':
            return jsonify({'error': 'This unit is not open for interest'}), 400
        # Only the CRM's own customer fields (+ reference) are accepted; nothing else is stored.
        body = {k: data.get(k) for k in CUSTOMER_KEYS if k in data}
        try:
            fields = leads.parse_customer_fields(body, require_core=True)
            fields['customer_birthday'] = leads.birthday_value(body.get('birthday'))
        except ValidationError as exc:
            return jsonify(exc.payload()), exc.status
        panorama_id = _resolve_panorama(sb, root, tree)
        if not panorama_id:
            return jsonify({'error': 'This project is not connected to the CRM yet'}), 409
        # Reference works exactly like the plotted-development checkout.
        requested_ref = str(data.get('reference_user_id') or '').strip()
        reference_user_id, catalog, reference_row = _validate_project_reference_user(
            sb, reference_user_id=requested_ref, panorama_id=panorama_id,
        )
        if requested_ref and not reference_user_id:
            return jsonify({'error': 'Selected reference is not available for this project', 'field': 'reference_user_id'}), 400
        client_id = None
        if reference_row and (reference_row.get('client_ids') or []):
            client_id = str(reference_row['client_ids'][0])
        if not client_id:
            client_ids = list((catalog or {}).get('client_ids') or [])
            client_id = str(client_ids[0]) if len(client_ids) == 1 else None
        reference_role = (
            _normalize_client_member_role((reference_row or {}).get('member_role'))
            or (leads.resolve_reference_user_role(sb, reference_user_id, client_id) if reference_user_id else None)
        )
        if not reference_user_id:
            # No reference chosen: the interest belongs to the client team via its admin.
            reference_user_id, reference_role = leads.default_reference_for_client(sb, client_id)

        trail = [z['name'] for _m, z in path if z.get('name')]
        meta = zone['meta']
        area = meta.get('area') or ''
        if not area and meta.get('size_min'):
            area = f"{meta['size_min']}" + (f" - {meta['size_max']}" if meta.get('size_max') and meta['size_max'] != meta['size_min'] else '') + ' Sq. Ft.'
        snapshot = [{
            'name': ' › '.join(trail) or zone['name'],
            'area': area,
            'price': meta.get('price') or '',
            'status': unit_status,
            'source': 'building_plan',
            'building_map_id': target_map['id'],
            'zone_id': zone['id'],
            'unit_type': meta.get('unit_type') or meta.get('configurations') or '',
        }]
        now = leads.now_iso()
        row = {
            'record_status': leads.STATUS_INTEREST,
            'org_id': root.get('org_id'),
            'panorama_id': panorama_id,
            'client_id': client_id,
            'submitted_by': None,
            'reference_user_id': reference_user_id,
            'reference_user_role': _normalize_client_member_role(reference_role) or None,
            'plots': snapshot,
            'notes': '',
            'custom_fields': {},
            'created_at': now,
            'updated_at': now,
        }
        for key, value in fields.items():
            row[key] = leads.text_or_null(key, value)
        row['category'] = BUILDING_PLAN_CATEGORY
        row['lead_source'] = 'SalesTool'
        try:
            r = sb.table(leads.LEAD_TABLE).insert(row).execute()
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500
        crm_cache_bump()
        created = (r.data or [row])[0]
        return jsonify({'success': True, 'id': created.get('id')}), 201

    @app.route('/api/building-maps/flow', methods=['GET'])
    @require_admin
    def api_building_maps_flow(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        q = sb.table('building_maps').select('*').eq('user_id', str(user_id)).order('created_at', desc=True)
        workspace_id = str(request.args.get('workspace_id') or '').strip()
        if workspace_id:
            q = q.eq('workspace_id', workspace_id)
        maps = q.execute().data or []
        zones_by_map = bm_zones_for_maps(sb, [m['id'] for m in maps])
        base = (request.url_root or '').rstrip('/')
        urls = sign_many(get_building_map_s3_url, [m.get('image_filename') for m in maps], verify=False)
        out = []
        for m in maps:
            zs = zones_by_map.get(str(m['id']), [])
            out.append({
                'id': m['id'],
                'name': m.get('name') or '',
                'workspace_id': m.get('workspace_id'),
                'image_url': urls.get(m.get('image_filename')),
                'view_config': normalize_view_config(m.get('view_config')),
                'share_url': f"{base}/building-plan/{m.get('share_token', '')}",
                'zones': [{
                    'id': z['id'],
                    'name': z.get('name') or '',
                    'floor': z.get('floor_number') or 0,
                    'link': zone_link_type(z),
                    'target': z.get('linked_building_map_id'),
                    'floor_plan_item_id': z.get('linked_floor_plan_item_id'),
                    'panorama_id': z.get('linked_panorama_id'),
                    'status': normalize_zone_meta(z.get('meta')).get('status') or '',
                } for z in zs],
            })
        return jsonify(out)
