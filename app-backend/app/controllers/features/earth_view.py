"""
Earth View routes (moved out of register.py).
"""

from flask import jsonify, render_template, request

from app.core.auth import get_profile, require_admin
from app.core.concurrency import outcome, run_parallel
from app.core.database import get_supabase
from app.services.earth_view_service import count_plots_and_markers as ev_count_plots_and_markers, create_earth_view as ev_create, create_marker as ev_create_marker, create_plot as ev_create_plot, delete_earth_view as ev_delete, delete_marker as ev_delete_marker, delete_plot as ev_delete_plot, get_earth_view as ev_get, get_earth_view_by_token as ev_get_by_token, get_marker as ev_get_marker, get_plot as ev_get_plot, list_earth_views as ev_list, list_markers as ev_list_markers, list_plots as ev_list_plots, update_earth_view as ev_update, update_marker as ev_update_marker, update_plot as ev_update_plot
from app.services.workspace_service import can_manage_workspace, get_workspace_by_id

from .shared import auth_ctx


def register_earth_view_routes(app):
    @app.route('/api/earth-views', methods=['GET'])
    @require_admin
    def api_list_earth_views(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        workspace_id = str(request.args.get('workspace_id') or '').strip() or None
        views = ev_list(sb, user_id, workspace_id=workspace_id)
        base = (request.url_root or '').rstrip('/')
        counts = ev_count_plots_and_markers(sb, [view['id'] for view in views])
        for view in views:
            view['share_url'] = f"{base}/earth-view/view/{view.get('share_token', '')}"
            view['plot_count'], view['marker_count'] = counts.get(str(view['id']), (0, 0))
        return jsonify(views)

    @app.route('/api/earth-views', methods=['POST'])
    @require_admin
    def api_create_earth_view(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or 'Earth View').strip() or 'Earth View'
        workspace_id = str(data.get('workspace_id') or '').strip() or None
        if workspace_id:
            workspace = get_workspace_by_id(sb, workspace_id)
            if not workspace:
                return jsonify({'error': 'Project not found'}), 404
            if not can_manage_workspace(sb, workspace, user_id, role):
                return jsonify({'error': 'Forbidden'}), 403
        existing = ev_list(sb, user_id, workspace_id=workspace_id)
        if any(v.get('name', '').strip().lower() == name.lower() for v in existing):
            return jsonify({'error': f'An earth view named "{name}" already exists'}), 409
        center_lng = data.get('center_lng', 0)
        center_lat = data.get('center_lat', 20)
        zoom = data.get('zoom', 3)
        profile = get_profile(sb, user_id)
        org_id = profile.get('org_id') if profile else None
        view = ev_create(sb, user_id, org_id, name, center_lng, center_lat, zoom, workspace_id=workspace_id)
        if not view:
            return jsonify({'error': 'Failed to create earth view'}), 500
        base = (request.url_root or '').rstrip('/')
        view['share_url'] = f"{base}/earth-view/view/{view.get('share_token', '')}"
        return jsonify(view), 201

    @app.route('/api/earth-views/<view_id>', methods=['GET'])
    @require_admin
    def api_get_earth_view(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        # Plots and markers only need view_id: they load alongside the view (and its owner check).
        view, plots, markers = run_parallel(
            outcome(lambda: ev_get(sb, view_id)),
            outcome(lambda: ev_list_plots(sb, view_id)),
            outcome(lambda: ev_list_markers(sb, view_id)),
        )
        view = view.get()
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        view['plots'] = plots.get()
        view['markers'] = markers.get()
        base = (request.url_root or '').rstrip('/')
        view['share_url'] = f"{base}/earth-view/view/{view.get('share_token', '')}"
        return jsonify(view)

    @app.route('/api/earth-views/<view_id>', methods=['PATCH'])
    @require_admin
    def api_update_earth_view(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        for key in ('name', 'center_lng', 'center_lat', 'zoom'):
            if key in data:
                updates[key] = data[key]
        if updates:
            ev_update(sb, view_id, **updates)
        updated = ev_get(sb, view_id)
        return jsonify(updated)

    @app.route('/api/earth-views/<view_id>', methods=['DELETE'])
    @require_admin
    def api_delete_earth_view(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        ev_delete(sb, view_id)
        return jsonify({'success': True})

    @app.route('/api/earth-views/<view_id>/plots', methods=['GET'])
    @require_admin
    def api_list_earth_view_plots(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        return jsonify(ev_list_plots(sb, view_id))

    @app.route('/api/earth-views/<view_id>/plots', methods=['POST'])
    @require_admin
    def api_create_earth_view_plot(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        points = data.get('points', [])
        if not isinstance(points, list) or len(points) < 3:
            return jsonify({'error': 'At least 3 points required'}), 400
        plot = ev_create_plot(
            sb,
            view_id,
            name,
            points,
            area=str(data.get('area') or '').strip(),
            price=str(data.get('price') or '').strip(),
            status=str(data.get('status') or 'available').strip(),
            description=str(data.get('description') or '').strip(),
            color=str(data.get('color') or 'green').strip(),
            media_photo=str(data.get('media_photo') or '').strip(),
            media_video=str(data.get('media_video') or '').strip(),
            linked_panorama_id=data.get('linked_panorama_id') or None,
            sort_order=int(data.get('sort_order') or 0),
        )
        if not plot:
            return jsonify({'error': 'Failed to create plot'}), 500
        return jsonify(plot), 201

    @app.route('/api/earth-view-plots/<int:plot_id>', methods=['PUT'])
    @require_admin
    def api_update_earth_view_plot(user_id, role, plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        plot = ev_get_plot(sb, plot_id)
        if not plot:
            return jsonify({'error': 'Not found'}), 404
        view = ev_get(sb, plot.get('earth_view_id'))
        if not view or (str(view.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        for key in ('name', 'area', 'price', 'status', 'description', 'color', 'media_photo',
                    'media_video', 'points', 'linked_panorama_id', 'sort_order'):
            if key in data:
                updates[key] = data[key]
        if updates:
            ev_update_plot(sb, plot_id, **updates)
        updated = ev_get_plot(sb, plot_id)
        return jsonify(updated)

    @app.route('/api/earth-view-plots/<int:plot_id>', methods=['DELETE'])
    @require_admin
    def api_delete_earth_view_plot(user_id, role, plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        plot = ev_get_plot(sb, plot_id)
        if not plot:
            return jsonify({'error': 'Not found'}), 404
        view = ev_get(sb, plot.get('earth_view_id'))
        if not view or (str(view.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        ev_delete_plot(sb, plot_id)
        return jsonify({'success': True})

    @app.route('/api/earth-views/<view_id>/markers', methods=['GET'])
    @require_admin
    def api_list_earth_view_markers(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        return jsonify(ev_list_markers(sb, view_id))

    @app.route('/api/earth-views/<view_id>/markers', methods=['POST'])
    @require_admin
    def api_create_earth_view_marker(user_id, role, view_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get(sb, view_id)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        if str(view.get('user_id')) != str(user_id) and role != 'superadmin':
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        name = str(data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        if data.get('longitude') is None or data.get('latitude') is None:
            return jsonify({'error': 'longitude and latitude are required'}), 400
        marker = ev_create_marker(
            sb,
            view_id,
            name,
            data.get('longitude'),
            data.get('latitude'),
            description=str(data.get('description') or '').strip(),
            marker_color=str(data.get('marker_color') or '#4ade80').strip(),
            linked_panorama_id=data.get('linked_panorama_id') or None,
            media_photo=str(data.get('media_photo') or '').strip(),
            media_video=str(data.get('media_video') or '').strip(),
        )
        if not marker:
            return jsonify({'error': 'Failed to create marker'}), 500
        return jsonify(marker), 201

    @app.route('/api/earth-view-markers/<marker_id>', methods=['PUT'])
    @require_admin
    def api_update_earth_view_marker(user_id, role, marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        marker = ev_get_marker(sb, marker_id)
        if not marker:
            return jsonify({'error': 'Not found'}), 404
        view = ev_get(sb, marker.get('earth_view_id'))
        if not view or (str(view.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        data = request.get_json(silent=True) or {}
        updates = {}
        for key in ('name', 'description', 'marker_color', 'linked_panorama_id', 'media_photo',
                    'media_video', 'longitude', 'latitude'):
            if key in data:
                updates[key] = data[key]
        if updates:
            ev_update_marker(sb, marker_id, **updates)
        updated = ev_get_marker(sb, marker_id)
        return jsonify(updated)

    @app.route('/api/earth-view-markers/<marker_id>', methods=['DELETE'])
    @require_admin
    def api_delete_earth_view_marker(user_id, role, marker_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        marker = ev_get_marker(sb, marker_id)
        if not marker:
            return jsonify({'error': 'Not found'}), 404
        view = ev_get(sb, marker.get('earth_view_id'))
        if not view or (str(view.get('user_id')) != str(user_id) and role != 'superadmin'):
            return jsonify({'error': 'Forbidden'}), 403
        ev_delete_marker(sb, marker_id)
        return jsonify({'success': True})

    @app.route('/earth-view/admin/<view_id>')
    def earth_view_admin_page(view_id):
        return render_template('earth_view_admin.html', view_id=view_id, **auth_ctx())

    @app.route('/earth-view/view/<share_token>')
    def earth_view_public_view(share_token):
        sb = get_supabase()
        if not sb:
            return "Database not configured", 503
        view = ev_get_by_token(sb, share_token)
        if not view:
            return "Not found", 404
        plots, markers, all_views = run_parallel(
            lambda: ev_list_plots(sb, view['id']),
            lambda: ev_list_markers(sb, view['id']),
            lambda: ev_list(sb, view['user_id']),
            strict=True,
        )
        siblings = []
        for ev in all_views:
            siblings.append({
                'id': ev['id'],
                'name': ev.get('name', ''),
                'share_token': ev.get('share_token', ''),
                'active': ev['id'] == view['id'],
            })
        return render_template(
            'earth_view_customer.html',
            earth_view=view,
            plots=plots,
            markers=markers,
            siblings=siblings,
        )

    @app.route('/api/public/earth-view/<share_token>')
    def api_public_earth_view(share_token):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        view = ev_get_by_token(sb, share_token)
        if not view:
            return jsonify({'error': 'Not found'}), 404
        view['plots'], view['markers'] = run_parallel(
            lambda: ev_list_plots(sb, view['id']),
            lambda: ev_list_markers(sb, view['id']),
            strict=True,
        )
        return jsonify(view)
