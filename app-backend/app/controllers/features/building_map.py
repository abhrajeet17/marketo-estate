"""
Building Map routes (moved out of register.py).
"""

import uuid

from flask import jsonify, redirect, render_template, request

from app.core.auth import get_profile, require_admin
from app.core.concurrency import run_parallel
from app.core.database import get_supabase
from app.services.building_map_service import batch_create_zones as bm_batch_create_zones, create_building_map as bm_create, create_image as bm_create_image, create_zone as bm_create_zone, delete_building_map as bm_delete, delete_image as bm_delete_image, delete_zone as bm_delete_zone, get_building_map as bm_get, get_building_map_by_token as bm_get_by_token, get_image as bm_get_image, get_next_image_sort_order as bm_next_image_sort, get_zone as bm_get_zone, list_building_maps as bm_list, list_images as bm_list_images, list_zones as bm_list_zones, list_zones_for_image as bm_list_zones_for_image, list_zones_for_maps as bm_list_zones_for_maps, update_building_map as bm_update, update_image as bm_update_image, update_zone as bm_update_zone
from app.services.floorplan_service import get_item as fp_get_item
from app.services.storage_service import MAX_BUILDING_MAP_READ_BYTES, compress_building_map_image, delete_building_map_from_s3, get_building_map_s3_url, get_floorplan_s3_url, make_image_placeholder, upload_building_map_to_s3
from app.services.workspace_service import can_manage_workspace, get_workspace_by_id

from .building_plan import invalidate_building_plan_cache, sign_many as _sign_many
from .shared import allowed_file, auth_ctx


def register_building_map_routes(app):
    @app.route('/api/building-maps', methods=['GET'])
    @require_admin
    def api_list_building_maps(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        maps = bm_list(sb, user_id)
        base = (request.url_root or '').rstrip('/')
        cat_ids = sorted({str(m['catalogue_id']) for m in maps if m.get('catalogue_id')})
        # Zones and catalogue names both key off the map rows: one parallel round-trip.
        zones_by_map, cat_rows = run_parallel(
            lambda: bm_list_zones_for_maps(sb, [m['id'] for m in maps]),
            lambda: sb.table('floor_plan_catalogues').select('id, name').in_('id', cat_ids).execute().data or [] if cat_ids else [],
            strict=True,
        )
        cat_names = {str(c['id']): c.get('name') or '' for c in cat_rows}
        urls = _sign_many(get_building_map_s3_url, [m.get('image_filename') for m in maps], verify=False)
        for m in maps:
            m['image_url'] = urls.get(m.get('image_filename'))
            m['share_url'] = f"{base}/building-plan/{m.get('share_token', '')}"
            zones = zones_by_map.get(str(m['id']), [])
            m['zone_count'] = len(zones)
            m['floor_count'] = len(set(z.get('floor_number', 0) for z in zones))
            m['catalogue_name'] = cat_names.get(str(m.get('catalogue_id') or ''), '')
        return jsonify(maps)

    @app.route('/api/building-maps', methods=['POST'])
    @require_admin
    def api_create_building_map(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        name = str(request.form.get('name') or 'Building Map').strip()
        existing = bm_list(sb, user_id)
        if any(m.get('name', '').strip().lower() == name.lower() for m in existing):
            return jsonify({'error': f'A building map named "{name}" already exists'}), 409
        catalogue_id = str(request.form.get('catalogue_id') or '').strip() or None
        workspace_id = str(request.form.get('workspace_id') or '').strip() or None
        if workspace_id:
            workspace = get_workspace_by_id(sb, workspace_id)
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            if not can_manage_workspace(sb, workspace, user_id, role):
                return jsonify({'error': 'Forbidden'}), 403
        f = request.files.get('file')
        if not f:
            return jsonify({'error': 'No file uploaded'}), 400
        if not allowed_file(f.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        raw_bytes = f.read()
        if not raw_bytes or len(raw_bytes) > MAX_BUILDING_MAP_READ_BYTES:
            return jsonify({'error': 'File too large'}), 400
        jpeg_bytes, w, h = compress_building_map_image(raw_bytes)
        if not jpeg_bytes:
            return jsonify({'error': 'Failed to process image'}), 400
        filename = f"bm_{uuid.uuid4().hex[:16]}.jpg"
        upload_building_map_to_s3(filename, jpeg_bytes, 'image/jpeg')
        profile = get_profile(sb, user_id)
        org_id = profile.get('org_id') if profile else None
        bm = bm_create(sb, user_id, org_id, name, filename, w, h, catalogue_id, workspace_id=workspace_id)
        if not bm:
            return jsonify({'error': 'Failed to create building map'}), 500
        view_config = {}
        level = str(request.form.get('level') or '').strip().lower()
        if level in ('aerial', 'tower', 'floor'):
            view_config['level'] = level
        lqip = make_image_placeholder(jpeg_bytes)
        if lqip:
            view_config['lqip'] = lqip
        if view_config:
            try:
                updated = bm_update(sb, bm['id'], view_config=view_config)
                if updated:
                    bm['view_config'] = updated.get('view_config')
            except ValueError:
                pass  # view_config column missing: type and preview are optional
        bm['image_url'] = get_building_map_s3_url(filename)
        base = (request.url_root or '').rstrip('/')
        bm['share_url'] = f"{base}/building-plan/{bm.get('share_token', '')}"
        return jsonify(bm), 201

    @app.route('/api/building-maps/<map_id>', methods=['GET'])
    @require_admin
    def api_get_building_map(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        bm['image_url'] = get_building_map_s3_url(bm.get('image_filename'))
        zones = bm_list_zones(sb, map_id)
        bm['zones'] = zones
        base = (request.url_root or '').rstrip('/')
        bm['share_url'] = f"{base}/building-plan/{bm.get('share_token', '')}"
        return jsonify(bm)

    @app.route('/api/building-maps/<map_id>', methods=['PATCH'])
    @require_admin
    def api_update_building_map(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'name' in data:
            updates['name'] = str(data['name']).strip()
        if 'catalogue_id' in data:
            updates['catalogue_id'] = str(data['catalogue_id'] or '').strip() or None
        if 'view_config' in data:
            incoming = data['view_config'] if isinstance(data['view_config'], dict) else {}
            # The blurred preview is server-generated: keep it across settings saves.
            merged = dict(incoming)
            existing_lqip = (bm.get('view_config') or {}).get('lqip')
            if existing_lqip and 'lqip' not in merged:
                merged['lqip'] = existing_lqip
            updates['view_config'] = merged
        if 'name' in updates and not updates['name']:
            return jsonify({'error': 'Name is required'}), 400
        if updates:
            try:
                bm_update(sb, map_id, **updates)
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 409
            invalidate_building_plan_cache()
        updated = bm_get(sb, map_id)
        if updated:
            updated['image_url'] = get_building_map_s3_url(updated.get('image_filename'))
        return jsonify(updated)

    @app.route('/api/building-maps/<map_id>', methods=['DELETE'])
    @require_admin
    def api_delete_building_map(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        delete_building_map_from_s3(bm.get('image_filename'))
        bm_delete(sb, map_id)
        invalidate_building_plan_cache()
        return jsonify({'success': True})

    # -- Building Map Images --

    @app.route('/api/building-maps/<map_id>/images', methods=['GET'])
    @require_admin
    def api_list_building_map_images(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        images = bm_list_images(sb, map_id)
        for img in images:
            img['image_url'] = get_building_map_s3_url(img.get('image_filename'))
            img['zone_count'] = len(bm_list_zones_for_image(sb, img['id']))
        return jsonify(images)

    @app.route('/api/building-maps/<map_id>/images', methods=['POST'])
    @require_admin
    def api_create_building_map_image(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        name = str(request.form.get('name') or 'View').strip()
        f = request.files.get('file')
        if not f:
            return jsonify({'error': 'No file uploaded'}), 400
        if not allowed_file(f.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        raw_bytes = f.read()
        if not raw_bytes or len(raw_bytes) > MAX_BUILDING_MAP_READ_BYTES:
            return jsonify({'error': 'File too large'}), 400
        jpeg_bytes, w, h = compress_building_map_image(raw_bytes)
        if not jpeg_bytes:
            return jsonify({'error': 'Failed to process image'}), 400
        filename = f"bmi_{uuid.uuid4().hex[:16]}.jpg"
        upload_building_map_to_s3(filename, jpeg_bytes, 'image/jpeg')
        sort_order = bm_next_image_sort(sb, map_id)
        img = bm_create_image(sb, map_id, name, filename, w, h, sort_order)
        if not img:
            return jsonify({'error': 'Failed to create image'}), 500
        img['image_url'] = get_building_map_s3_url(filename)
        return jsonify(img), 201

    @app.route('/api/building-map-images/<image_id>', methods=['PATCH'])
    @require_admin
    def api_update_building_map_image(user_id, role, image_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        img = bm_get_image(sb, image_id)
        if not img:
            return jsonify({'error': 'Not found'}), 404
        bm = bm_get(sb, img['building_map_id'])
        if not bm or (str(bm.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        if 'name' in data:
            updates['name'] = str(data['name']).strip()
        if 'sort_order' in data:
            updates['sort_order'] = int(data['sort_order'])
        if updates:
            bm_update_image(sb, image_id, **updates)
        updated = bm_get_image(sb, image_id)
        if updated:
            updated['image_url'] = get_building_map_s3_url(updated.get('image_filename'))
        return jsonify(updated)

    @app.route('/api/building-map-images/<image_id>', methods=['DELETE'])
    @require_admin
    def api_delete_building_map_image(user_id, role, image_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        img = bm_get_image(sb, image_id)
        if not img:
            return jsonify({'error': 'Not found'}), 404
        bm = bm_get(sb, img['building_map_id'])
        if not bm or (str(bm.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        delete_building_map_from_s3(img.get('image_filename'))
        bm_delete_image(sb, image_id)
        return jsonify({'success': True})

    # -- Building Zones --

    def _zone_link_fields(sb, bm, data, user_id, role, zone_id=None):
        """One link per zone: building map, floor plan or panorama. Returns (fields, error_response)."""
        link_type = str(data.get('link_type') or '').strip()
        pano = data.get('linked_panorama_id') or None
        fp_item = data.get('linked_floor_plan_item_id') or None
        target = str(data.get('linked_building_map_id') or '').strip() or None
        if not link_type:
            link_type = 'building_map' if target else 'floor_plan' if fp_item else 'panorama' if pano else ''
        if link_type not in ('', 'panorama', 'floor_plan', 'building_map'):
            return None, (jsonify({'error': 'Invalid link type'}), 400)
        fields = {'link_type': link_type, 'linked_panorama_id': None,
                  'linked_floor_plan_item_id': None, 'linked_building_map_id': None}
        if link_type == 'building_map':
            if not target:
                return None, (jsonify({'error': 'Pick the building map this zone opens', 'field': 'linked_building_map_id'}), 400)
            if str(target) == str(bm['id']):
                return None, (jsonify({'error': 'A zone cannot open its own building map'}), 400)
            target_map = bm_get(sb, target)
            if not target_map or (str(target_map.get('user_id')) != str(bm.get('user_id')) and role != 'superadmin'):
                return None, (jsonify({'error': 'Building map not found'}), 404)
            fields['linked_building_map_id'] = target
        elif link_type == 'floor_plan':
            if not fp_item:
                return None, (jsonify({'error': 'Pick a floor plan', 'field': 'linked_floor_plan_item_id'}), 400)
            fields['linked_floor_plan_item_id'] = str(fp_item)
        elif link_type == 'panorama':
            if not pano:
                return None, (jsonify({'error': 'Pick a panorama', 'field': 'linked_panorama_id'}), 400)
            fields['linked_panorama_id'] = int(pano)
        return fields, None

    @app.route('/api/building-maps/<map_id>/zones', methods=['GET'])
    @require_admin
    def api_list_building_zones(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        zones = bm_list_zones(sb, map_id)
        return jsonify(zones)

    @app.route('/api/building-maps/<map_id>/zones', methods=['POST'])
    @require_admin
    def api_create_building_zone(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        points = data.get('points', [])
        if not isinstance(points, list) or len(points) < 3:
            return jsonify({'error': 'At least 3 points required'}), 400
        floor_number = int(data.get('floor_number', 0))
        color = str(data.get('color', 'green')).strip()
        link_fields, link_err = _zone_link_fields(sb, bm, data, user_id, role)
        if link_err:
            return link_err
        sort_order = int(data.get('sort_order', 0))
        image_id = data.get('image_id') or None
        try:
            zone = bm_create_zone(sb, map_id, name, floor_number, points, color,
                                  link_fields.get('linked_panorama_id'),
                                  link_fields.get('linked_floor_plan_item_id'), sort_order,
                                  image_id=image_id,
                                  link_type=link_fields.get('link_type'),
                                  linked_building_map_id=link_fields.get('linked_building_map_id'),
                                  meta=data.get('meta') if 'meta' in data else None)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 409
        if not zone:
            return jsonify({'error': 'Failed to create zone'}), 500
        invalidate_building_plan_cache()
        return jsonify(zone), 201

    @app.route('/api/building-maps/<map_id>/zones/batch', methods=['POST'])
    @require_admin
    def api_batch_create_building_zones(user_id, role, map_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get(sb, map_id)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        if str(bm.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        zones_data = data.get('zones', [])
        if not isinstance(zones_data, list) or not zones_data:
            return jsonify({'error': 'zones must be a non-empty list'}), 400
        if len(zones_data) > 120:
            return jsonify({'error': 'At most 120 zones per batch'}), 400
        checked_links = {}  # identical links (e.g. 41 floors -> one typical floor) are validated once
        for z in zones_data:
            if not isinstance(z.get('points', []), list) or len(z.get('points', [])) < 3:
                return jsonify({'error': 'Each zone needs at least 3 points'}), 400
            if any(k in z for k in ('link_type', 'linked_panorama_id', 'linked_floor_plan_item_id', 'linked_building_map_id')):
                key = tuple(str(z.get(k) or '') for k in ('link_type', 'linked_panorama_id', 'linked_floor_plan_item_id', 'linked_building_map_id'))
                if key not in checked_links:
                    link_fields, link_err = _zone_link_fields(sb, bm, z, user_id, role)
                    if link_err:
                        return link_err
                    checked_links[key] = link_fields
                z.update(checked_links[key])
        try:
            created = bm_batch_create_zones(sb, map_id, zones_data)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 409
        invalidate_building_plan_cache()
        return jsonify(created), 201

    @app.route('/api/building-zones/<int:zone_id>', methods=['PUT'])
    @require_admin
    def api_update_building_zone(user_id, role, zone_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        zone = bm_get_zone(sb, zone_id)
        if not zone:
            return jsonify({'error': 'Not found'}), 404
        bm = bm_get(sb, zone['building_map_id'])
        if not bm or (str(bm.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        for k in ('name', 'floor_number', 'color', 'sort_order', 'points', 'image_id', 'meta'):
            if k in data:
                updates[k] = data[k]
        if any(k in data for k in ('link_type', 'linked_panorama_id', 'linked_floor_plan_item_id', 'linked_building_map_id')):
            link_fields, link_err = _zone_link_fields(sb, bm, data, user_id, role, zone_id=zone_id)
            if link_err:
                return link_err
            updates.update(link_fields)
        if 'name' in updates and not str(updates['name'] or '').strip():
            return jsonify({'error': 'Name is required'}), 400
        if updates:
            try:
                bm_update_zone(sb, zone_id, **updates)
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 409
            invalidate_building_plan_cache()
        updated = bm_get_zone(sb, zone_id)
        return jsonify(updated)

    @app.route('/api/building-zones/<int:zone_id>', methods=['DELETE'])
    @require_admin
    def api_delete_building_zone(user_id, role, zone_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        zone = bm_get_zone(sb, zone_id)
        if not zone:
            return jsonify({'error': 'Not found'}), 404
        bm = bm_get(sb, zone['building_map_id'])
        if not bm or (str(bm.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        bm_delete_zone(sb, zone_id)
        invalidate_building_plan_cache()
        return jsonify({'success': True})

    # -- Building Map pages --

    @app.route('/building-plans')
    def building_plans_page():
        return render_template('building_plans.html', **auth_ctx())

    @app.route('/building-map/admin/<map_id>')
    def building_map_admin_page(map_id):
        return render_template('building_map_admin.html', map_id=map_id, **auth_ctx())

    @app.route('/building-map/view/<share_token>')
    def building_map_public_view(share_token):
        return redirect(f'/building-plan/{share_token}')

    # -- Public API for building map data (used by customer view JS) --

    @app.route('/api/public/building-map/<share_token>')
    def api_public_building_map(share_token):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        bm = bm_get_by_token(sb, share_token)
        if not bm:
            return jsonify({'error': 'Not found'}), 404
        bm['image_url'] = get_building_map_s3_url(bm.get('image_filename'))
        zones = bm_list_zones(sb, bm['id'])
        for z in zones:
            if z.get('linked_floor_plan_item_id'):
                fp_item = fp_get_item(sb, z['linked_floor_plan_item_id'])
                if fp_item:
                    z['linked_floor_plan_image_url'] = get_floorplan_s3_url(fp_item.get('image_filename'))
                    z['linked_floor_plan_name'] = fp_item.get('name', '')
        bm['zones'] = zones
        return jsonify(bm)
