"""
Project Plan routes (moved out of register.py).
"""

from flask import jsonify, render_template, request

from app.core.auth import require_auth
from app.core.concurrency import outcome, run_parallel
from app.core.database import get_supabase
from app.services.building_map_service import get_building_map as bm_get, list_zones as bm_list_zones
from app.services.floorplan_service import get_item as fp_get_item
from app.services.full_view_service import get_config_for_workspace as fv_get_config
from app.services.project_plan_service import add_map_to_plan as pp_add_map, create_project_plan as pp_create, delete_project_plan as pp_delete, get_next_plan_map_sort_order as pp_next_sort, get_project_plan as pp_get, get_project_plan_by_token as pp_get_by_token, list_maps_for_plans as pp_list_maps_for_plans, list_plan_maps as pp_list_maps, list_project_plans as pp_list, remove_map_from_plan as pp_remove_map, reorder_plan_maps as pp_reorder, update_project_plan as pp_update
from app.services.storage_service import get_building_map_s3_url, get_floorplan_s3_url
from app.services.workspace_service import can_manage_workspace, get_workspace_by_id


# Building-map columns the plan-map link responses expose.
_LINK_MAP_FIELDS = 'name, image_filename, share_token'
_PLAN_BUILDING_FIELDS = (
    '*, building_zones!building_zones_building_map_id_fkey(*, floor_plan_items(name, image_filename))'
)


def _zone_order(zone):
    # Same order as list_zones(): floor_number, sort_order ascending, NULLs last.
    return tuple((zone.get(k) is None, zone.get(k) or 0) for k in ('floor_number', 'sort_order'))


def plan_buildings(sb, plan_id):
    """Building maps of a plan for the public view, each with its zones and linked floor plans."""
    buildings = []
    for links in pp_list_maps_for_plans(sb, [plan_id], _PLAN_BUILDING_FIELDS).values():
        for link in links:
            bm = link.get('building_maps')
            if not bm:
                continue
            bm = dict(bm)
            zones = sorted(bm.pop('building_zones', None) or [], key=_zone_order)
            bm['image_url'] = get_building_map_s3_url(bm.get('image_filename'))
            for z in zones:
                fp_item = z.pop('floor_plan_items', None)
                if z.get('linked_floor_plan_item_id') and fp_item:
                    z['linked_floor_plan_image_url'] = get_floorplan_s3_url(fp_item.get('image_filename'))
                    z['linked_floor_plan_name'] = fp_item.get('name', '')
            bm['zones'] = zones
            buildings.append(bm)
    return buildings


def register_project_plan_routes(app):
    @app.route('/api/project-plans', methods=['GET'])
    @require_auth
    def api_list_project_plans(user_id, role):
        sb = get_supabase()
        plans = pp_list(sb, user_id)
        workspace_id = str(request.args.get('workspace_id') or '').strip() or None
        if workspace_id:
            plans = [p for p in plans if str(p.get('workspace_id') or '') == workspace_id]
        base = (request.url_root or '').rstrip('/')
        # Every plan's maps, their building maps and zone floors in one query (was 1 + 2 per map).
        maps_by_plan = pp_list_maps_for_plans(
            sb, [p['id'] for p in plans],
            'name, building_zones!building_zones_building_map_id_fkey(floor_number)',
        )
        for p in plans:
            maps = maps_by_plan.get(str(p['id']), [])
            p['map_count'] = len(maps)
            map_names = []
            total_zones = 0
            total_floors = 0
            for link in maps:
                bm = link.get('building_maps')
                if bm:
                    map_names.append(bm.get('name', ''))
                    zones = bm.get('building_zones') or []
                    total_zones += len(zones)
                    total_floors += len(set(z.get('floor_number', 0) for z in zones))
            p['map_names'] = map_names
            p['total_zones'] = total_zones
            p['total_floors'] = total_floors
            p['share_url'] = f"{base}/project-plan/view/{p.get('share_token', '')}"
        return jsonify(plans)

    @app.route('/api/project-plans', methods=['POST'])
    @require_auth
    def api_create_project_plan(user_id, role):
        sb = get_supabase()
        data = request.get_json(force=True)
        name = data.get('name', 'Project Plan').strip() or 'Project Plan'
        existing = pp_list(sb, user_id)
        if any(p.get('name', '').strip().lower() == name.lower() for p in existing):
            return jsonify({'error': f'A project plan named "{name}" already exists'}), 409
        org_id = data.get('org_id')
        workspace_id = str(data.get('workspace_id') or '').strip() or None
        if workspace_id:
            workspace = get_workspace_by_id(sb, workspace_id)
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            if not can_manage_workspace(sb, workspace, user_id, role):
                return jsonify({'error': 'Forbidden'}), 403
        plan = pp_create(sb, user_id, org_id, name, workspace_id=workspace_id)
        if not plan:
            return jsonify({'error': 'Failed to create project plan'}), 500
        plan['share_url'] = request.host_url.rstrip('/') + '/project-plan/view/' + plan.get('share_token', '')
        return jsonify(plan), 201

    @app.route('/api/project-plans/<plan_id>', methods=['GET'])
    @require_auth
    def api_get_project_plan(user_id, role, plan_id):
        sb = get_supabase()
        # The plan and its maps (building maps embedded) load in one parallel round-trip.
        plan, maps_by_plan = run_parallel(
            outcome(lambda: pp_get(sb, plan_id)),
            outcome(lambda: pp_list_maps_for_plans(sb, [plan_id], _LINK_MAP_FIELDS)),
        )
        plan = plan.get()
        if not plan:
            return jsonify({'error': 'Not found'}), 404
        plan['maps'] = [link for links in maps_by_plan.get().values() for link in links]
        # Enrich maps with building map details
        for link in plan['maps']:
            bm = link.pop('building_maps', None)
            if bm:
                link['building_map_name'] = bm.get('name', '')
                link['building_map_image_url'] = get_building_map_s3_url(bm.get('image_filename'))
                link['building_map_share_token'] = bm.get('share_token', '')
        plan['share_url'] = request.host_url.rstrip('/') + '/project-plan/view/' + plan.get('share_token', '')
        return jsonify(plan)

    @app.route('/api/project-plans/<plan_id>', methods=['PATCH'])
    @require_auth
    def api_update_project_plan(user_id, role, plan_id):
        sb = get_supabase()
        data = request.get_json(force=True)
        updated = pp_update(sb, plan_id, **data)
        if not updated:
            return jsonify({'error': 'Not found or no valid fields'}), 404
        return jsonify(updated)

    @app.route('/api/project-plans/<plan_id>', methods=['DELETE'])
    @require_auth
    def api_delete_project_plan(user_id, role, plan_id):
        sb = get_supabase()
        deleted = pp_delete(sb, plan_id)
        if not deleted:
            return jsonify({'error': 'Not found'}), 404
        return jsonify({'ok': True})

    # -- Plan ↔ Map linking --

    @app.route('/api/project-plans/<plan_id>/maps', methods=['GET'])
    @require_auth
    def api_list_plan_maps(user_id, role, plan_id):
        sb = get_supabase()
        maps = [link for links in pp_list_maps_for_plans(sb, [plan_id], _LINK_MAP_FIELDS).values() for link in links]
        for link in maps:
            bm = link.pop('building_maps', None)
            if bm:
                link['building_map_name'] = bm.get('name', '')
                link['building_map_image_url'] = get_building_map_s3_url(bm.get('image_filename'))
                link['building_map_share_token'] = bm.get('share_token', '')
        return jsonify(maps)

    @app.route('/api/project-plans/<plan_id>/maps', methods=['POST'])
    @require_auth
    def api_add_map_to_plan(user_id, role, plan_id):
        sb = get_supabase()
        data = request.get_json(force=True)
        building_map_id = data.get('building_map_id')
        if not building_map_id:
            return jsonify({'error': 'building_map_id required'}), 400
        sort_order = pp_next_sort(sb, plan_id)
        link = pp_add_map(sb, plan_id, building_map_id, sort_order)
        if not link:
            return jsonify({'error': 'Failed to add map'}), 500
        return jsonify(link), 201

    @app.route('/api/project-plans/<plan_id>/maps/<building_map_id>', methods=['DELETE'])
    @require_auth
    def api_remove_map_from_plan(user_id, role, plan_id, building_map_id):
        sb = get_supabase()
        pp_remove_map(sb, plan_id, building_map_id)
        return jsonify({'ok': True})

    @app.route('/api/project-plans/<plan_id>/maps/reorder', methods=['POST'])
    @require_auth
    def api_reorder_plan_maps(user_id, role, plan_id):
        sb = get_supabase()
        data = request.get_json(force=True)
        ordered_ids = data.get('ordered_map_ids', [])
        result = pp_reorder(sb, plan_id, ordered_ids)
        return jsonify(result)

    # -- Public Project Plan view --

    @app.route('/project-plan/view/<share_token>')
    def project_plan_public_view(share_token):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        plan = pp_get_by_token(sb, share_token)
        if not plan:
            return "Not found", 404
        workspace_id = str((plan or {}).get('workspace_id') or '').strip()
        # Buildings (with zones and linked floor plans embedded) and the Full View style are
        # independent: one parallel round-trip instead of 1 + 2 per building + 1 per zone.
        buildings, fv_cfg = run_parallel(
            lambda: plan_buildings(sb, plan['id']),
            lambda: fv_get_config(sb, workspace_id) if workspace_id else None,
            strict=True,
        )
        fv_style = {}
        if fv_cfg and isinstance(fv_cfg.get('style'), dict):
            fv_style = fv_cfg.get('style')
        return render_template('project_plan_view.html',
                               plan=plan,
                               buildings=buildings,
                               fv_style=fv_style)
