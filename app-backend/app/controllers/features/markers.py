"""
Markers routes (moved out of register.py).
"""

from flask import jsonify

from app.core.concurrency import outcome, run_parallel
from app.core.database import get_supabase
from app.services.panorama_service import get_panorama_by_id


def register_marker_routes(app):
    @app.route('/api/public/panoramas/<int:panorama_id>/markers', methods=['GET'])
    def public_list_markers(panorama_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        style_columns_supported = True
        link_columns_supported = True
        link_mode_columns_supported = True
        image_columns_supported = True
        base_cols = ['id', 'plot_id', 'name', 'description', 'longitude', 'latitude', 'status', 'created_at']
        style_cols = ['marker_style', 'marker_icon', 'marker_color', 'rotation_x', 'rotation_y', 'rotation_z']
        link_cols = ['linked_panorama_id']
        link_mode_cols = ['link_mode']
        voiceover_columns_supported = True

        def build_columns():
            cols = list(base_cols)
            if image_columns_supported:
                cols.insert(4, 'image_filename')
            if voiceover_columns_supported:
                cols.append('voiceover_filename')
            if link_columns_supported:
                cols.extend(link_cols)
            if link_mode_columns_supported:
                cols.extend(link_mode_cols)
            if style_columns_supported:
                cols.extend(style_cols)
            return ', '.join(cols)

        def is_style_column_error(err):
            msg = str(err).lower()
            return 'marker_style' in msg or 'marker_icon' in msg or 'marker_color' in msg

        def is_link_column_error(err):
            msg = str(err).lower()
            return 'linked_panorama_id' in msg or 'linked panorama' in msg

        def is_link_mode_column_error(err):
            msg = str(err).lower()
            return 'link_mode' in msg and ('does not exist' in msg or 'column' in msg)

        def is_image_column_error(err):
            msg = str(err).lower()
            return 'image_filename' in msg

        def is_voiceover_column_error(err):
            msg = str(err).lower()
            return 'voiceover_filename' in msg and ('does not exist' in msg or 'column' in msg)

        def fetch_markers():
            return (
                sb.table('plot_markers')
                .select(build_columns())
                .eq('plot_id', str(panorama_id))
                .order('created_at', desc=False)
                .execute()
            )

        # The first markers query runs alongside the panorama check (discarded on a 404).
        panorama, first_attempt = run_parallel(
            lambda: get_panorama_by_id(sb, panorama_id),
            outcome(fetch_markers),
        )
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404

        last_error = None
        for _ in range(4):
            attempt, first_attempt = first_attempt, None
            try:
                r = attempt.get() if attempt is not None else fetch_markers()
                markers = r.data or []
                # Enrich with lock status
                try:
                    marker_ids = [str(m.get('id', '')) for m in markers if m.get('id')]
                    locked_ids = set()
                    if marker_ids:
                        for i in range(0, len(marker_ids), 50):
                            chunk = marker_ids[i:i+50]
                            lr = sb.table('plot_locks').select('plot_id').in_('plot_id', chunk).execute()
                            for row in (lr.data or []):
                                locked_ids.add(str(row.get('plot_id', '')))
                    for m in markers:
                        m['is_locked'] = str(m.get('id', '')) in locked_ids
                except Exception:
                    # If plot_locks table doesn't exist yet, just return without lock info
                    for m in markers:
                        m['is_locked'] = False
                return jsonify(markers)
            except Exception as e:
                last_error = e
                changed = False
                if style_columns_supported and is_style_column_error(e):
                    style_columns_supported = False
                    changed = True
                if link_columns_supported and is_link_column_error(e):
                    link_columns_supported = False
                    changed = True
                if link_mode_columns_supported and is_link_mode_column_error(e):
                    link_mode_columns_supported = False
                    changed = True
                if image_columns_supported and is_image_column_error(e):
                    image_columns_supported = False
                    changed = True
                if voiceover_columns_supported and is_voiceover_column_error(e):
                    voiceover_columns_supported = False
                    changed = True
                if not changed:
                    break
        return jsonify({'error': str(last_error or 'Failed to load markers')}), 500
