"""
Public project portal listing (/api/public/portal/projects).
"""
import json

from flask import jsonify, request

from app.core.concurrency import run_parallel
from app.core.database import get_supabase


def _search_filter(q, include_rera=True):
    fields = 'name.ilike.%{q}%,location_address.ilike.%{q}%,location_city.ilike.%{q}%,builder_name.ilike.%{q}%,description.ilike.%{q}%'
    if include_rera:
        fields += ',rera_registration.ilike.%{q}%'
    return fields.format(q=q)


def _empty_stats():
    return {'count': 0, 'prices': [], 'available': 0, 'sold': 0, 'hold': 0}


def _add_plot(stats, plot):
    stats['count'] += 1
    status = (plot.get('status') or '').lower()
    if status == 'available':
        stats['available'] += 1
    elif status == 'sold':
        stats['sold'] += 1
    elif status in ('on_hold', 'reserved'):
        stats['hold'] += 1
    price_str = str(plot.get('price') or '').strip()
    if price_str:
        try:
            numeric = float(''.join(c for c in price_str if c.isdigit() or c == '.'))
            if numeric > 0:
                stats['prices'].append(numeric)
        except (ValueError, TypeError):
            pass


def register_portal_routes(app):
    @app.route('/api/public/portal/projects', methods=['GET'])
    def public_portal_projects():
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        q = request.args.get('q', '').strip()
        city = request.args.get('city', '').strip()
        project_type = request.args.get('type', '').strip()
        sort = request.args.get('sort', 'newest').strip()
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(50, max(1, int(request.args.get('per_page', 12))))
        offset_val = (page - 1) * per_page

        def fetch_rows():
            try:
                query = sb.table('workspaces').select('*').eq('is_published', True)
                if city:
                    query = query.ilike('location_city', f'%{city}%')
                if project_type:
                    query = query.eq('project_type', project_type)
                if q:
                    query = query.or_(_search_filter(q))
                query = query.order('created_at', desc=(sort != 'oldest'))
                return list(query.range(offset_val, offset_val + per_page - 1).execute().data or [])
            except Exception as e:
                return e

        def fetch_total():
            # Only used when the page comes back full (see below); fetched up front so it does
            # not cost an extra round-trip.
            count_q = sb.table('workspaces').select('id', count='exact').eq('is_published', True)
            if city:
                count_q = count_q.ilike('location_city', f'%{city}%')
            if project_type:
                count_q = count_q.eq('project_type', project_type)
            if q:
                count_q = count_q.or_(_search_filter(q, include_rera=False))
            return {'count': getattr(count_q.execute(), 'count', None)}  # None from run_parallel = failed

        def fetch_cities():
            cities, seen = [], set()
            for r in (sb.table('workspaces').select('location_city').eq('is_published', True).execute().data or []):
                c = (r.get('location_city') or '').strip()
                if c and c not in seen:
                    seen.add(c)
                    cities.append(c)
            cities.sort()
            return cities

        # Round-trip 1: the page, its total and the city list are independent.
        rows, total_count, cities = run_parallel(fetch_rows, fetch_total, fetch_cities)
        if isinstance(rows, Exception):
            msg = str(rows).lower()
            if 'does not exist' in msg or 'column' in msg or '42703' in msg:
                return jsonify({'projects': [], 'total': 0, 'page': page, 'per_page': per_page, 'cities': []})
            return jsonify({'error': str(rows)}), 500
        rows = rows or []

        workspace_ids = [str(r.get('id')) for r in rows if r.get('id')]
        main_pano_ids = [r.get('main_panorama_id') for r in rows if r.get('main_panorama_id')]
        org_ids = list(set(r.get('org_id') for r in rows if r.get('org_id')))

        # Round-trip 2: main panoramas, each project's panoramas with their plots embedded
        # (plots.panorama_id FK), and organisations.
        main_rows, ws_panos, org_rows = run_parallel(
            lambda: sb.table('panoramas').select('id, filename, is_360').in_('id', main_pano_ids).execute().data or [] if main_pano_ids else [],
            lambda: sb.table('panoramas').select('id, workspace_id, plots(panorama_id, id, price, status)').in_('workspace_id', workspace_ids).execute().data or [],
            lambda: sb.table('organizations').select('id, name, accent_color').in_('id', org_ids).execute().data or [] if org_ids else [],
        )
        main_panos = {int(p.get('id')): p for p in main_rows or []}
        org_map = {org['id']: org for org in org_rows or []}

        ws_plot_stats = {}
        for p in ws_panos or []:
            agg = ws_plot_stats.setdefault(str(p.get('workspace_id') or ''), _empty_stats())
            for plot in p.get('plots') or []:
                _add_plot(agg, plot)

        projects = []
        for row in rows:
            ws_id = str(row.get('id'))
            main_id = row.get('main_panorama_id')
            main_pano = main_panos.get(int(main_id), {}) if main_id else {}
            stats = ws_plot_stats.get(ws_id, _empty_stats())
            prices = stats['prices']
            avg_price = sum(prices) / len(prices) if prices else 0
            min_price = min(prices) if prices else 0
            max_price = max(prices) if prices else 0
            org = org_map.get(row.get('org_id'), {})
            amenities = row.get('amenities') or []
            if isinstance(amenities, str):
                try:
                    amenities = json.loads(amenities)
                except Exception:
                    amenities = []

            projects.append({
                'id': ws_id,
                'main_panorama_id': int(main_id) if main_id else None,
                'name': row.get('name', ''),
                'filename': main_pano.get('filename', ''),
                'is_360': bool(main_pano.get('is_360')),
                'location_address': row.get('location_address', ''),
                'location_city': row.get('location_city', ''),
                'location_state': row.get('location_state', ''),
                'location_lat': row.get('location_lat'),
                'location_lng': row.get('location_lng'),
                'rera_registration': row.get('rera_registration', ''),
                'launch_date': str(row.get('launch_date') or ''),
                'possession_date': row.get('possession_date', ''),
                'builder_name': row.get('builder_name', ''),
                'project_type': row.get('project_type', 'residential'),
                'total_area': row.get('total_area', ''),
                'description': row.get('description', ''),
                'amenities': amenities,
                'contact_phone': row.get('contact_phone', ''),
                'contact_email': row.get('contact_email', ''),
                'google_maps_link': row.get('google_maps_link', ''),
                'org_name': org.get('name', ''),
                'org_accent': org.get('accent_color', '#c9a962'),
                'plot_count': stats['count'],
                'available_plots': stats['available'],
                'sold_plots': stats['sold'],
                'hold_plots': stats['hold'],
                'avg_price': round(avg_price, 2),
                'min_price': round(min_price, 2),
                'max_price': round(max_price, 2),
                'created_at': str(row.get('created_at') or ''),
                'updated_at': str(row.get('updated_at') or ''),
            })

        total = len(projects)
        if len(rows) == per_page:
            if total_count is None:
                total = offset_val + len(projects) + 1
            else:
                total = total_count['count'] or len(projects)

        return jsonify({
            'projects': projects,
            'total': total,
            'page': page,
            'per_page': per_page,
            'cities': cities or [],
        })
