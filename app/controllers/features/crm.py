from datetime import datetime
import re
import time
import uuid

from flask import jsonify, request

from app import config as app_config
from app.core.auth import get_profile, require_admin, require_auth
from app.core.database import get_supabase, is_transient_supabase_error, require_supabase, with_supabase_retry
from app.services.access_policy import _chunks, annotate_resource_rows_with_client_scope, get_client_memberships
from app.services.email_service import send_email as send_smtp_email
from app.controllers.features.crm_pagination import (
    crm_page_payload,
    crm_parse_page_args,
    crm_parse_sort_args,
    crm_sort_rows,
)

CRM_CONTACT_SORT_FIELDS = ('full_name', 'email', 'phone', 'birthday', 'address', 'updated_at', 'created_at')
# Email/phone are blanked for reference-scoped brokers; sorting by them would
# expose the hidden ordering.
CRM_CONTACT_SORT_FIELDS_MASKED = ('full_name', 'birthday', 'updated_at', 'created_at')
CRM_PLOT_SORT_FIELDS = ('name', 'area', 'status', 'description', 'panorama_name', 'workspace_name')
from app.services.plot_service import get_plot_panorama_id, update_plot as plot_update
from app.services.uam_reference_service import (
    CLIENT_MEMBER_ROLE_BROKER,
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    _is_broker_member_role,
    _normalize_client_member_role,
    _project_reference_client_ids,
    broker_shareable_workspace_ids,
    user_is_broker,
    user_is_client_admin,
)

CRM_MASTER_APPLIES_ENTITIES = ('interests', 'deals', 'contacts', 'plots', 'projects')

CRM_MASTER_FIELDS = [
    {'key': 'lead_source', 'label': 'Lead Source', 'sort_order': 10, 'required': True, 'optional': False, 'applies_to': ['interests', 'deals']},
    {'key': 'lead_category', 'label': 'Lead Category', 'sort_order': 20, 'required': True, 'optional': False, 'applies_to': ['interests']},
    {'key': 'lead_status', 'label': 'Lead Status', 'sort_order': 30, 'required': True, 'optional': False, 'applies_to': ['interests', 'deals']},
    {'key': 'campaign_type', 'label': 'Campaign Type', 'sort_order': 40, 'required': False, 'optional': True, 'applies_to': ['interests']},
    {'key': 'campaign_status', 'label': 'Campaign Status', 'sort_order': 50, 'required': False, 'optional': True, 'applies_to': ['interests']},
    {'key': 'deal_stage', 'label': 'Deal Stage', 'sort_order': 60, 'required': False, 'optional': True, 'applies_to': ['deals']},
    {'key': 'plot_status', 'label': 'Plot Status', 'sort_order': 65, 'required': False, 'optional': True, 'applies_to': ['plots']},
    {'key': 'builder_name', 'label': 'Builder Name', 'sort_order': 68, 'required': False, 'optional': True, 'applies_to': ['projects']},
    {'key': 'title', 'label': 'Title', 'sort_order': 70, 'required': False, 'optional': True, 'applies_to': ['contacts']},
    {'key': 'state', 'label': 'State', 'sort_order': 80, 'required': False, 'optional': True, 'applies_to': ['interests', 'contacts']},
    {'key': 'country', 'label': 'Country', 'sort_order': 90, 'required': False, 'optional': True, 'applies_to': ['interests', 'contacts']},
]

CRM_MASTER_DEFAULT_VALUES = {
    'lead_source': [
        'Partner', 'Word of Mouth', 'Web Download', 'Website', 'WhatsApp Campaign',
        'Google Ad', 'Facebook Ad', 'Cold Call', 'Email Response', 'Public Relations',
        'Facebook', 'YouTube', 'Networking', 'India Mart', 'Just Dial',
    ],
    'lead_category': [
        'Single', 'Married', 'Married with Children', 'Looking to Split from Family',
        'IT Employee', 'Businessman', 'Self Employed',
    ],
    'lead_status': [
        'Cold Lead', 'Warm Lead - Inquiring', 'Hot Lead - Purchased in Existing Project',
        'Lost Lead - Lost after Quotation', 'Repeat Client - Loyal Buyer',
    ],
    'campaign_type': ['WhatsApp Campaign', 'Google Ad', 'Facebook Ad', 'Email Campaign', 'Public Relations'],
    'campaign_status': ['Draft', 'Active', 'Paused', 'Completed', 'Disabled'],
    'deal_stage': ['New', 'Contacted', 'Site Visit', 'Negotiation', 'Won', 'Lost'],
    'plot_status': ['Available', 'On Hold', 'Sold'],
    'builder_name': ['Sun Builders', 'Skyline Developers', 'Greenfield Realty'],
    'title': ['Mr', 'Mrs', 'Ms', 'Dr'],
    'state': [],
    'country': ['India'],
}

_CRM_MASTER_CONFIG_CACHE = {}
_CRM_MASTER_CONFIG_CACHE_TTL_SECONDS = 10
_CRM_ALLOTTED_CLIENTS_CACHE = {}
_CRM_ALLOTTED_CLIENTS_CACHE_TTL_SECONDS = 10


def _with_retry(fn, attempts=2, sleep_seconds=0.12):
    last_error = None
    for idx in range(max(1, int(attempts))):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if idx >= max(1, int(attempts)) - 1:
                break
            time.sleep(sleep_seconds)
    if last_error is not None:
        raise last_error
    return fn()


def _fetch_pages(fetch_page, page_size=1000):
    rows = []
    start = 0
    while True:
        batch = fetch_page(start, start + page_size - 1) or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        start += page_size


def register_crm_broker_routes(app, *, crm_panorama_ids, crm_client_scope_ids):
    @app.route('/api/crm/allotted-clients', methods=['GET'])
    @require_auth
    def list_allotted_clients(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        cache_key = ('allotted_clients', str(user_id), str(role or ''))
        cached = _CRM_ALLOTTED_CLIENTS_CACHE.get(cache_key)
        if cached and time.time() - cached[0] <= _CRM_ALLOTTED_CLIENTS_CACHE_TTL_SECONDS:
            return jsonify(cached[1])

        all_memberships = get_client_memberships(sb, user_id)
        client_admin_memberships = [
            row for row in all_memberships
            if _normalize_client_member_role(row.get('member_role')) == CLIENT_MEMBER_ROLE_CLIENT_ADMIN
        ]
        broker_memberships = [
            row for row in all_memberships
            if _normalize_client_member_role(row.get('member_role')) == CLIENT_MEMBER_ROLE_BROKER
        ]
        is_client_admin = bool(client_admin_memberships)
        memberships = client_admin_memberships if is_client_admin else broker_memberships
        if not memberships and _normalize_client_member_role(role) != CLIENT_MEMBER_ROLE_BROKER:
            return jsonify([])

        client_scope_ids = crm_client_scope_ids(sb, user_id, role)
        client_ids = [m.get('client_id') for m in memberships if m.get('client_id')]
        if client_scope_ids is not None:
            client_ids = [cid for cid in client_ids if cid in client_scope_ids]
        client_ids = list(dict.fromkeys(client_ids))
        if not client_ids:
            return jsonify([])

        member_ids_by_client = {cid: [] for cid in client_ids}
        if is_client_admin:
            try:
                for chunk in _chunks(client_ids):
                    rows = (
                        sb.table('client_members')
                        .select('id, client_id')
                        .in_('client_id', chunk)
                        .execute()
                        .data or []
                    )
                    for row in rows:
                        cid = str(row.get('client_id') or '')
                        mid = row.get('id')
                        if cid in member_ids_by_client and mid:
                            member_ids_by_client[cid].append(mid)
            except Exception:
                pass
        else:
            for member in memberships:
                cid = member.get('client_id')
                mid = member.get('id')
                if cid in member_ids_by_client and mid:
                    member_ids_by_client[cid].append(mid)

        client_names = {}
        try:
            for chunk in _chunks(client_ids):
                rows = sb.table('clients').select('id, name').in_('id', chunk).execute().data or []
                for row in rows:
                    cid = str(row.get('id') or '')
                    if cid:
                        client_names[cid] = str(row.get('name') or '').strip() or cid
        except Exception:
            client_names = {}

        project_sets = {cid: set() for cid in client_ids}
        panorama_sets = {cid: set() for cid in client_ids}
        for cid, member_ids in member_ids_by_client.items():
            for chunk in _chunks(member_ids):
                try:
                    rows = sb.table('workspace_access').select('workspace_id').in_('client_member_id', chunk).execute().data or []
                    for row in rows:
                        wsid = row.get('workspace_id')
                        if wsid:
                            project_sets[cid].add(str(wsid))
                except Exception:
                    pass
                try:
                    rows = sb.table('panorama_access').select('panorama_id').in_('client_member_id', chunk).execute().data or []
                    for row in rows:
                        pid = row.get('panorama_id')
                        try:
                            if pid is not None:
                                panorama_sets[cid].add(int(pid))
                        except Exception:
                            continue
                except Exception:
                    pass

        workspace_to_clients = {}
        for cid, workspace_ids in project_sets.items():
            for workspace_id in workspace_ids:
                workspace_to_clients.setdefault(workspace_id, set()).add(cid)
        if workspace_to_clients:
            try:
                for chunk in _chunks(workspace_to_clients.keys()):
                    rows = sb.table('panoramas').select('id, workspace_id').in_('workspace_id', chunk).execute().data or []
                    for row in rows:
                        try:
                            pid = int(row.get('id'))
                        except Exception:
                            continue
                        wsid = str(row.get('workspace_id') or '')
                        for cid in workspace_to_clients.get(wsid, set()):
                            panorama_sets.setdefault(cid, set()).add(pid)
            except Exception:
                pass

        direct_panorama_to_clients = {}
        for cid, panorama_ids in panorama_sets.items():
            for panorama_id in panorama_ids:
                direct_panorama_to_clients.setdefault(panorama_id, set()).add(cid)
        if direct_panorama_to_clients:
            try:
                for chunk in _chunks(direct_panorama_to_clients.keys()):
                    rows = sb.table('panoramas').select('id, workspace_id').in_('id', chunk).execute().data or []
                    for row in rows:
                        try:
                            pid = int(row.get('id'))
                        except Exception:
                            continue
                        wsid = row.get('workspace_id')
                        if wsid:
                            for cid in direct_panorama_to_clients.get(pid, set()):
                                project_sets.setdefault(cid, set()).add(str(wsid))
            except Exception:
                pass

        plot_counts = {
            cid: {'total': 0, 'sold': 0, 'pending': 0, 'available': 0}
            for cid in client_ids
        }
        panorama_to_clients = {}
        for cid, panorama_ids in panorama_sets.items():
            for panorama_id in panorama_ids:
                panorama_to_clients.setdefault(panorama_id, set()).add(cid)
        if panorama_to_clients:
            try:
                for chunk in _chunks(panorama_to_clients.keys()):
                    rows = sb.table('plots').select('panorama_id, status').in_('panorama_id', chunk).execute().data or []
                    for row in rows:
                        try:
                            pid = int(row.get('panorama_id'))
                        except Exception:
                            continue
                        status_key = _crm_plot_status_key(row.get('status'))
                        for cid in panorama_to_clients.get(pid, set()):
                            counts = plot_counts[cid]
                            counts['total'] += 1
                            if status_key == 'sold':
                                counts['sold'] += 1
                            elif status_key in ('reserved', 'onhold', 'pending'):
                                counts['pending'] += 1
                            elif status_key == 'available':
                                counts['available'] += 1
            except Exception:
                pass

        lead_counts = {cid: 0 for cid in client_ids}
        contact_sets = {cid: set() for cid in client_ids}
        try:
            for chunk in _chunks(client_ids):
                def fetch_interest_page(start, end):
                    query = (
                        sb.table('buy_interests')
                        .select('client_id, contact_id')
                        .in_('client_id', chunk)
                    )
                    if not is_client_admin:
                        query = query.eq('reference_user_id', str(user_id))
                    return query.range(start, end).execute().data or []

                rows = _fetch_pages(fetch_interest_page)
                for row in rows:
                    cid = str(row.get('client_id') or '')
                    if cid not in lead_counts:
                        continue
                    lead_counts[cid] += 1
                    contact_id = row.get('contact_id')
                    if contact_id:
                        contact_sets[cid].add(str(contact_id))
        except Exception:
            pass

        out = []
        for cid in client_ids:
            out.append({
                'client_id': cid,
                'client_name': client_names.get(cid) or cid,
                'member_role': next((m.get('member_role') for m in memberships if m.get('client_id') == cid), ''),
                'project_count': len(project_sets.get(cid) or set()),
                'lead_count': int(lead_counts.get(cid, 0)),
                'interest_count': int(lead_counts.get(cid, 0)),
                'contact_count': len(contact_sets.get(cid) or set()),
                'plot_count': int(plot_counts.get(cid, {}).get('total', 0)),
                'sold_plot_count': int(plot_counts.get(cid, {}).get('sold', 0)),
                'pending_plot_count': int(plot_counts.get(cid, {}).get('pending', 0)),
                'available_plot_count': int(plot_counts.get(cid, {}).get('available', 0)),
            })
        out.sort(key=lambda row: row.get('client_name') or '')
        _CRM_ALLOTTED_CLIENTS_CACHE[cache_key] = (time.time(), out)
        if len(_CRM_ALLOTTED_CLIENTS_CACHE) > 128:
            oldest_key = min(_CRM_ALLOTTED_CLIENTS_CACHE, key=lambda key: _CRM_ALLOTTED_CLIENTS_CACHE[key][0])
            _CRM_ALLOTTED_CLIENTS_CACHE.pop(oldest_key, None)
        return jsonify(out)


def _crm_plot_status_key(status):
    return re.sub(r'[^a-z]', '', str(status or '').lower())


def _crm_plot_status_canonical(status):
    """Collapse hold-family aliases so the filter matches stored rows.

    Plots are written with status='on_hold' (see update_crm_plot below), but
    the Plotted List's Hold filter option sends status=hold. Without this,
    _crm_plot_status_key('hold') == 'hold' while _crm_plot_status_key('on_hold')
    == 'onhold', so the Hold filter never matched any row.
    """
    key = _crm_plot_status_key(status)
    if key in ('hold', 'onhold', 'reserved'):
        return 'onhold'
    return key


def _crm_load_all_plots(sb, pano_ids, *, crm_cache_get, crm_cache_set, crm_cache_version, user_id, role):
    cache_key = (
        'crm_plots',
        crm_cache_version.get('v', 1),
        str(user_id),
        str(role or ''),
        tuple(pano_ids),
    )
    cached = crm_cache_get(cache_key, ttl_seconds=5)
    if cached is not None:
        return cached

    pano_rows = []
    pano_by_id = {}
    all_plots = []
    for chunk in _chunks(pano_ids):
        try:
            panos_r = (
                sb.table('panoramas')
                .select('id, name, workspace_id, is_360')
                .in_('id', chunk)
                .execute()
            )
            for row in (panos_r.data or []):
                pano_rows.append(row)
                try:
                    pano_by_id[int(row.get('id'))] = row
                except Exception:
                    continue
        except Exception:
            pass
        try:
            plots_r = (
                sb.table('plots')
                .select('id, panorama_id, name, area, price, status, description')
                .in_('panorama_id', chunk)
                .execute()
            )
            all_plots.extend(plots_r.data or [])
        except Exception:
            pass

    annotated_panos = annotate_resource_rows_with_client_scope(sb, pano_rows, 'panorama')
    pano_scope = {}
    ws_ids_needed = set()
    for row in annotated_panos:
        try:
            pano_scope[int(row.get('id'))] = {
                'client_ids': [str(cid) for cid in (row.get('client_ids') or []) if cid],
                'client_names': [str(name) for name in (row.get('client_names') or []) if name],
            }
        except Exception:
            continue
        wsid = row.get('workspace_id')
        if wsid:
            ws_ids_needed.add(str(wsid))

    ws_names = {}
    if ws_ids_needed:
        ws_list = list(ws_ids_needed)
        for i in range(0, len(ws_list), 100):
            chunk = ws_list[i:i + 100]
            try:
                wr = sb.table('workspaces').select('id, name').in_('id', chunk).execute()
                for row in (wr.data or []):
                    ws_names[str(row.get('id'))] = str(row.get('name') or '')
            except Exception:
                pass

    for plot in all_plots:
        try:
            pid = int(plot.get('panorama_id'))
        except Exception:
            pid = None
        pano = pano_by_id.get(pid) or {}
        scope = pano_scope.get(pid) or {}
        wsid = pano.get('workspace_id')
        plot['panorama_name'] = pano.get('name') or ('Project #' + str(pid or ''))
        plot['panorama_id'] = pid
        plot['is_360'] = bool(pano.get('is_360'))
        plot['workspace_id'] = str(wsid) if wsid else None
        plot['workspace_name'] = ws_names.get(str(wsid), '') if wsid else ''
        plot['client_ids'] = scope.get('client_ids') or []
        plot['client_names'] = scope.get('client_names') or []

    crm_cache_set(cache_key, all_plots)
    return all_plots


def _crm_plot_filter_options(rows):
    """Project/Sector dropdown options derived from the plots that actually exist."""
    projects_map = {}
    sectors_map = {}
    for plot in rows or []:
        wsid = str(plot.get('workspace_id') or '').strip()
        wsname = str(plot.get('workspace_name') or '').strip()
        if wsid and wsname and wsid not in projects_map:
            projects_map[wsid] = wsname
        pano_id = plot.get('panorama_id')
        if pano_id is None:
            continue
        pano_key = str(pano_id)
        if pano_key in sectors_map:
            continue
        pano_name = str(plot.get('panorama_name') or '').strip()
        if pano_name:
            sectors_map[pano_key] = {'id': pano_id, 'name': pano_name, 'workspace_id': wsid or None}
    projects_out = [{'id': wsid, 'name': name} for wsid, name in projects_map.items()]
    projects_out.sort(key=lambda item: str(item.get('name') or '').lower())
    sectors_out = list(sectors_map.values())
    sectors_out.sort(key=lambda item: str(item.get('name') or '').lower())
    return {'projects': projects_out, 'sectors': sectors_out}


def register_crm_plot_routes(app, *, crm_panorama_ids, crm_cache_get, crm_cache_set, crm_cache_version, crm_cache_bump=None):
    def _broker_share_workspace_ids(sb, user_id, role):
        """Workspace ids an external broker can share, or None when unrestricted."""
        if str(role or '').strip().lower() in ('admin', 'superadmin'):
            return None
        cache_key = (
            'crm_plots_broker_scope',
            crm_cache_version.get('v', 1),
            str(user_id),
            str(role or ''),
        )
        cached = crm_cache_get(cache_key, ttl_seconds=8)
        if cached is None:
            restricted = user_is_broker(sb, user_id, role) and not user_is_client_admin(sb, user_id)
            cached = {
                'restricted': restricted,
                'workspace_ids': sorted(broker_shareable_workspace_ids(sb, user_id)) if restricted else [],
            }
            crm_cache_set(cache_key, cached)
        return set(cached.get('workspace_ids') or []) if cached.get('restricted') else None

    @app.route('/api/crm/plots', methods=['GET'])
    @require_auth
    def list_crm_all_plots(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        pano_ids = crm_panorama_ids(sb, user_id, role)
        if not pano_ids:
            payload = crm_page_payload([], 0, 1, 10)
            payload['filter_options'] = _crm_plot_filter_options([])
            return jsonify(payload)
        page, limit, offset = crm_parse_page_args(default_limit=10, max_limit=100)
        q = str(request.args.get('q') or '').strip().lower()
        client_id = str(request.args.get('client_id') or '').strip()
        workspace_id = str(request.args.get('workspace_id') or '').strip()
        panorama_id = str(request.args.get('panorama_id') or '').strip()
        status = _crm_plot_status_canonical(request.args.get('status') or '')

        all_plots = _crm_load_all_plots(
            sb,
            pano_ids,
            crm_cache_get=crm_cache_get,
            crm_cache_set=crm_cache_set,
            crm_cache_version=crm_cache_version,
            user_id=user_id,
            role=role,
        )
        rows = list(all_plots or [])
        # External brokers only see plots they can actually share a reference
        # link for (the workspace share-endpoint would 403 on anything else).
        share_ws_ids = _broker_share_workspace_ids(sb, user_id, role)
        if share_ws_ids is not None:
            rows = [p for p in rows if str(p.get('workspace_id') or '') in share_ws_ids]
        # Dropdown facets come from the full visible set, not the filtered page,
        # so picking a project never hides the other options.
        filter_options = _crm_plot_filter_options(rows)
        if q:
            rows = [
                p for p in rows
                if q in ' '.join([
                    str(p.get('name') or ''),
                    str(p.get('area') or ''),
                    str(p.get('status') or ''),
                    str(p.get('description') or ''),
                    str(p.get('panorama_name') or ''),
                    str(p.get('workspace_name') or ''),
                ]).lower()
            ]
        if client_id:
            rows = [p for p in rows if client_id in [str(cid) for cid in (p.get('client_ids') or [])]]
        if workspace_id:
            rows = [p for p in rows if str(p.get('workspace_id') or '') == workspace_id]
        if panorama_id:
            rows = [p for p in rows if str(p.get('panorama_id') or '') == panorama_id]
        if status:
            rows = [p for p in rows if _crm_plot_status_canonical(p.get('status')) == status]
        plot_sort_field, plot_sort_desc = crm_parse_sort_args(CRM_PLOT_SORT_FIELDS)
        if plot_sort_field:
            rows = crm_sort_rows(rows, plot_sort_field, plot_sort_desc)
        total = len(rows)
        page_rows = rows[offset:offset + limit]
        payload = crm_page_payload(page_rows, total, page, limit)
        payload['filter_options'] = filter_options
        return jsonify(payload)

    @app.route('/api/crm/plots/<int:plot_id>', methods=['PUT', 'PATCH'])
    @require_auth
    def update_crm_plot(user_id, role, plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        if not data:
            return jsonify({'error': 'Body required'}), 400

        panorama_id = get_plot_panorama_id(sb, plot_id)
        if not panorama_id:
            return jsonify({'error': 'Plot not found'}), 404
        try:
            panorama_id_int = int(panorama_id)
        except Exception:
            return jsonify({'error': 'Plot not found'}), 404

        allowed_pano_ids = set(int(pid) for pid in (crm_panorama_ids(sb, user_id, role) or []))
        if panorama_id_int not in allowed_pano_ids:
            return jsonify({'error': 'Forbidden'}), 403

        payload = {}
        for key in ('area', 'status', 'description'):
            if key in data:
                payload[key] = data.get(key)

        if not payload:
            return jsonify({'error': 'No editable fields provided'}), 400

        if 'status' in payload:
            status_key = _crm_plot_status_key(payload.get('status'))
            if status_key in ('hold', 'onhold', 'reserved'):
                payload['status'] = 'on_hold'
            elif status_key == 'sold':
                payload['status'] = 'sold'
            elif status_key == 'available':
                payload['status'] = 'available'
            else:
                payload['status'] = str(payload.get('status') or 'available').strip() or 'available'

        try:
            plot_update(sb, plot_id, payload)
            if callable(crm_cache_bump):
                crm_cache_bump()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


def register_crm_lock_routes(
    app,
    *,
    crm_panorama_ids,
    crm_client_scope_ids,
    crm_cache_get,
    crm_cache_set,
    crm_cache_version,
    crm_cache_bump,
):
    def _manual_lock_panorama_ids_for_user(sb, uid):
        try:
            rows = sb.table('plot_lock_access').select('panorama_id').eq('user_id', uid).execute().data or []
            out = set()
            for row in rows:
                try:
                    if row.get('panorama_id') is not None:
                        out.add(int(row.get('panorama_id')))
                except Exception:
                    continue
            return out
        except Exception:
            return set()

    def _is_auto_lock_eligible_member(member_role):
        normalized = _normalize_client_member_role(member_role)
        if normalized in (CLIENT_MEMBER_ROLE_CLIENT_USER, CLIENT_MEMBER_ROLE_BROKER):
            return True
        return _is_broker_member_role(normalized)

    def _auto_lock_panorama_ids_for_user(sb, uid, user_role):
        memberships = get_client_memberships(sb, uid)
        if not memberships:
            return set()
        scoped_client_ids = crm_client_scope_ids(sb, uid, user_role)
        eligible = False
        for member in memberships:
            if scoped_client_ids is not None and str(member.get('client_id') or '') not in scoped_client_ids:
                continue
            if _is_auto_lock_eligible_member(member.get('member_role')):
                eligible = True
                break
        if not eligible:
            return set()
        return set(crm_panorama_ids(sb, uid, user_role) or [])

    def _has_lock_access_for_panorama(sb, uid, user_role, panorama_id):
        if panorama_id in _manual_lock_panorama_ids_for_user(sb, uid):
            return True
        return panorama_id in _auto_lock_panorama_ids_for_user(sb, uid, user_role)

    @app.route('/api/crm/lock-access', methods=['GET'])
    @require_admin
    def list_lock_access(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_id = request.args.get('panorama_id')
        if not panorama_id:
            return jsonify({'error': 'panorama_id required'}), 400
        try:
            panorama_id = int(panorama_id)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid panorama_id'}), 400
        try:
            r = sb.table('plot_lock_access').select('id, panorama_id, user_id, granted_by, created_at').eq('panorama_id', panorama_id).execute()
            return jsonify(r.data or [])
        except Exception as e:
            msg = str(e)
            if 'plot_lock_access' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'plot_lock_access table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/crm/lock-access', methods=['POST'])
    @require_admin
    def grant_lock_access(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        try:
            panorama_id = int(data.get('panorama_id'))
        except (ValueError, TypeError):
            return jsonify({'error': 'panorama_id required'}), 400
        target_user_id = str(data.get('user_id') or '').strip()
        if not target_user_id:
            return jsonify({'error': 'user_id required'}), 400
        profile = get_profile(sb, user_id) or {}
        org_id = profile.get('org_id')
        try:
            sb.table('plot_lock_access').upsert({
                'panorama_id': panorama_id,
                'user_id': target_user_id,
                'granted_by': user_id,
                'org_id': org_id,
            }, on_conflict='panorama_id,user_id').execute()
            crm_cache_bump()
            return jsonify({'success': True}), 201
        except Exception as e:
            msg = str(e)
            if 'plot_lock_access' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'plot_lock_access table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/crm/lock-access', methods=['DELETE'])
    @require_admin
    def revoke_lock_access(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        try:
            panorama_id = int(data.get('panorama_id'))
        except (ValueError, TypeError):
            return jsonify({'error': 'panorama_id required'}), 400
        target_user_id = str(data.get('user_id') or '').strip()
        if not target_user_id:
            return jsonify({'error': 'user_id required'}), 400
        try:
            sb.table('plot_lock_access').delete().eq('panorama_id', panorama_id).eq('user_id', target_user_id).execute()
            crm_cache_bump()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/crm/lockable-plots', methods=['GET'])
    @require_auth
    def list_lockable_plots(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503

        manual_panorama_ids = _manual_lock_panorama_ids_for_user(sb, user_id)
        auto_panorama_ids = _auto_lock_panorama_ids_for_user(sb, user_id, role)
        panorama_ids = sorted(manual_panorama_ids.union(auto_panorama_ids))
        if not panorama_ids:
            return jsonify([])

        cache_key = (
            'crm_lockable_plots',
            crm_cache_version.get('v', 1),
            str(user_id),
            str(role or ''),
            tuple(panorama_ids),
        )
        cached = crm_cache_get(cache_key, ttl_seconds=5)
        if cached is not None:
            return jsonify(cached)

        all_plots = []
        pano_names = {}
        for chunk in _chunks(panorama_ids):
            try:
                panos_r = sb.table('panoramas').select('id, name').in_('id', chunk).execute()
                for p in (panos_r.data or []):
                    pano_names[p['id']] = p.get('name') or ('Project #' + str(p['id']))
            except Exception:
                pass
            try:
                plots_r = sb.table('plots').select('id, panorama_id, name, area, price, status').in_('panorama_id', chunk).execute()
                all_plots.extend(plots_r.data or [])
            except Exception:
                pass

        locks_by_plot = {}
        plot_ids = [p['id'] for p in all_plots]
        if plot_ids:
            for chunk in _chunks(plot_ids):
                try:
                    locks_r = sb.table('plot_locks').select('*').in_('plot_id', chunk).execute()
                    for lock in (locks_r.data or []):
                        locks_by_plot[lock['plot_id']] = lock
                except Exception:
                    pass

        result = []
        for plot in all_plots:
            lock = locks_by_plot.get(plot['id'])
            result.append({
                **plot,
                'panorama_name': pano_names.get(plot.get('panorama_id'), ''),
                'lock': lock,
            })
        crm_cache_set(cache_key, result)
        return jsonify(result)

    @app.route('/api/crm/plots/<int:plot_id>/lock', methods=['POST'])
    @require_auth
    def lock_plot(user_id, role, plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            plot_r = sb.table('plots').select('panorama_id').eq('id', plot_id).limit(1).execute()
            if not plot_r.data:
                return jsonify({'error': 'Plot not found'}), 404
            panorama_id = int(plot_r.data[0]['panorama_id'])
        except Exception:
            return jsonify({'error': 'Plot not found'}), 404

        # Lock-access gate intentionally disabled per product decision.
        # UI visibility controls who can invoke lock actions.
        # if not _has_lock_access_for_panorama(sb, user_id, role, panorama_id):
        #     return jsonify({'error': 'No lock access for this panorama'}), 403

        # The per-user lock-access allowlist stays off, but the caller must at
        # least be able to see this panorama in CRM — otherwise any account
        # could lock any plot platform-wide.
        try:
            allowed_pano_ids = set(int(pid) for pid in (crm_panorama_ids(sb, user_id, role) or []))
        except Exception:
            allowed_pano_ids = set()
        if panorama_id not in allowed_pano_ids:
            return jsonify({'error': 'Forbidden'}), 403

        data = request.get_json(silent=True) or {}
        lock_row = {
            'plot_id': plot_id,
            'locked_by': user_id,
            'locked_for_name': str(data.get('locked_for_name') or '').strip()[:120] or None,
            'locked_for_email': str(data.get('locked_for_email') or '').strip()[:254] or None,
        }
        try:
            sb.table('plot_locks').upsert(lock_row, on_conflict='plot_id').execute()
            crm_cache_bump()
            return jsonify({'success': True}), 201
        except Exception as e:
            msg = str(e)
            if 'plot_locks' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'plot_locks table not found. Run db/schema.sql in Supabase SQL Editor.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/crm/plots/<int:plot_id>/lock', methods=['DELETE'])
    @require_auth
    def unlock_plot(user_id, role, plot_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            lock_r = sb.table('plot_locks').select('id, locked_by').eq('plot_id', plot_id).limit(1).execute()
            if not lock_r.data:
                return jsonify({'error': 'Plot is not locked'}), 404
            if str(lock_r.data[0].get('locked_by')) != str(user_id) and role not in ('admin', 'superadmin'):
                return jsonify({'error': 'Only the user who locked this plot or an admin can unlock it'}), 403
            sb.table('plot_locks').delete().eq('plot_id', plot_id).execute()
            crm_cache_bump()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


def register_crm_master_routes(app, *, crm_client_scope_ids, crm_cache_bump):
    field_by_key = {row['key']: row for row in CRM_MASTER_FIELDS}

    def _normalize_master_field_key(raw):
        key = re.sub(r'[^a-z0-9_]+', '_', str(raw or '').strip().lower()).strip('_')
        if not key:
            return ''
        return key[:48]

    def _default_applies_to(field_key):
        base = field_by_key.get(field_key) or {}
        raw = base.get('applies_to') or ['interests']
        return [x for x in raw if x in CRM_MASTER_APPLIES_ENTITIES] or ['interests']

    def _normalize_applies_to(raw, field_key):
        if isinstance(raw, list):
            out = []
            for item in raw:
                token = str(item or '').strip().lower()
                if token in CRM_MASTER_APPLIES_ENTITIES and token not in out:
                    out.append(token)
            if out:
                return out
        return _default_applies_to(field_key)

    def _client_admin_ids(sb, uid):
        out = []
        for member in get_client_memberships(sb, uid):
            if _normalize_client_member_role(member.get('member_role')) == CLIENT_MEMBER_ROLE_CLIENT_ADMIN:
                cid = str(member.get('client_id') or '').strip()
                if cid and cid not in out:
                    out.append(cid)
        return out

    def _readable_client_ids(sb, uid, role):
        scoped = crm_client_scope_ids(sb, uid, role)
        if scoped is None:
            admin_ids = _client_admin_ids(sb, uid)
            return admin_ids, True
        return [str(cid) for cid in scoped if cid], False

    def _user_is_external_broker(sb, uid, role):
        if str(role or '').strip().lower() == 'broker':
            return True
        for member in get_client_memberships(sb, uid):
            if _is_broker_member_role(member.get('member_role')):
                return True
        return False

    def _is_admin_role(role):
        return str(role or '').strip().lower() in ('admin', 'superadmin')

    def _resolve_client_id(sb, uid, role, requested=None, require_admin=False, panorama_id=None):
        requested = str(requested or '').strip()
        if not requested and panorama_id is not None:
            try:
                pano_clients = _project_reference_client_ids(sb, panorama_id=int(panorama_id))
                if pano_clients:
                    requested = str(pano_clients[0])
            except Exception:
                pass
        if _is_admin_role(role) and requested:
            if str(role or '').strip().lower() == 'superadmin':
                return requested, None, None
            # Org-scoped admins may only touch clients in their own org — the
            # requested id is client input and must not cross org boundaries.
            try:
                caller_org = str((get_profile(sb, uid) or {}).get('org_id') or '')
                cr = sb.table('clients').select('id, org_id').eq('id', requested).limit(1).execute()
                client_rows = cr.data or []
                client_org = str((client_rows[0] or {}).get('org_id') or '') if client_rows else None
            except Exception:
                caller_org, client_org = '', None
            if client_org is None or not caller_org or client_org != caller_org:
                return None, jsonify({'error': 'Forbidden for this client'}), 403
            return requested, None, None
        allowed = _client_admin_ids(sb, uid) if require_admin else _readable_client_ids(sb, uid, role)[0]
        allowed = [str(cid) for cid in allowed if cid]
        if not allowed:
            return None, jsonify({'error': 'Client admin access required' if require_admin else 'No client access'}), 403
        if requested:
            if requested not in allowed:
                return None, jsonify({'error': 'Forbidden for this client'}), 403
            return requested, None, None
        return allowed[0], None, None

    def _wants_broker_scope(sb, uid, role, scope_hint, client_id_hint):
        scope_hint = str(scope_hint or '').strip().lower()
        client_id_hint = str(client_id_hint or '').strip()
        if scope_hint == 'client':
            return False
        if scope_hint == 'broker':
            return True
        if client_id_hint:
            return False
        return _user_is_external_broker(sb, uid, role)

    def _resolve_master_scope(sb, uid, role, *, scope_hint=None, client_id_hint=None, panorama_id=None, for_write=False):
        if _wants_broker_scope(sb, uid, role, scope_hint, client_id_hint):
            if not _user_is_external_broker(sb, uid, role):
                return None, jsonify({'error': 'Broker master access required'}), 403
            return {
                'scope': 'broker',
                'owner_user_id': str(uid),
                'client_id': None,
            }, None, None
        client_id, err, status = _resolve_client_id(
            sb, uid, role, client_id_hint, require_admin=for_write, panorama_id=panorama_id,
        )
        if err:
            return None, err, status
        return {
            'scope': 'client',
            'owner_user_id': None,
            'client_id': client_id,
        }, None, None

    def _seed_defaults(sb, master_scope):
        now = datetime.utcnow().isoformat()
        is_broker = master_scope['scope'] == 'broker'
        owner_user_id = master_scope.get('owner_user_id')
        client_id = master_scope.get('client_id')
        attr_existing = set()
        value_existing = set()
        attr_q = sb.table('crm_master_attributes').select('field_key')
        value_q = sb.table('crm_master_values').select('field_key, value')
        if is_broker:
            attr_q = attr_q.eq('owner_user_id', owner_user_id).is_('client_id', 'null')
            value_q = value_q.eq('owner_user_id', owner_user_id).is_('client_id', 'null')
        else:
            attr_q = attr_q.eq('client_id', client_id).is_('owner_user_id', 'null')
            value_q = value_q.eq('client_id', client_id).is_('owner_user_id', 'null')
        attr_rows = attr_q.execute().data or []
        attr_existing = {str(row.get('field_key') or '') for row in attr_rows}
        value_rows = value_q.execute().data or []
        value_existing = {(str(row.get('field_key') or ''), str(row.get('value') or '')) for row in value_rows}
        attr_inserts = []
        value_inserts = []
        for field in CRM_MASTER_FIELDS:
            if field['key'] not in attr_existing:
                row = {
                    'field_key': field['key'],
                    'label': field['label'],
                    'is_required': bool(field.get('required')),
                    'is_optional': bool(field.get('optional', True)),
                    'is_enabled': True,
                    'sort_order': int(field.get('sort_order') or 0),
                    'applies_to': _default_applies_to(field['key']),
                    'updated_at': now,
                }
                if is_broker:
                    row['owner_user_id'] = owner_user_id
                    row['client_id'] = None
                else:
                    row['client_id'] = client_id
                    row['owner_user_id'] = None
                attr_inserts.append(row)
            for idx, value in enumerate(CRM_MASTER_DEFAULT_VALUES.get(field['key'], [])):
                value_key = (field['key'], value)
                if value_key in value_existing:
                    continue
                row = {
                    'field_key': field['key'],
                    'value': value,
                    'is_enabled': True,
                    'sort_order': idx + 1,
                    'updated_at': now,
                }
                if is_broker:
                    row['owner_user_id'] = owner_user_id
                    row['client_id'] = None
                else:
                    row['client_id'] = client_id
                    row['owner_user_id'] = None
                value_inserts.append(row)
        if attr_inserts:
            sb.table('crm_master_attributes').insert(attr_inserts).execute()
        if value_inserts:
            sb.table('crm_master_values').insert(value_inserts).execute()

    def _master_cache_key(master_scope, include_disabled):
        return (
            str(master_scope.get('scope') or ''),
            str(master_scope.get('owner_user_id') or ''),
            str(master_scope.get('client_id') or ''),
            int(bool(include_disabled)),
        )

    def _master_cache_get(cache_key):
        entry = _CRM_MASTER_CONFIG_CACHE.get(cache_key)
        if not entry:
            return None
        created_at, payload = entry
        if time.time() - created_at > _CRM_MASTER_CONFIG_CACHE_TTL_SECONDS:
            _CRM_MASTER_CONFIG_CACHE.pop(cache_key, None)
            return None
        return payload

    def _master_cache_set(cache_key, payload):
        _CRM_MASTER_CONFIG_CACHE[cache_key] = (time.time(), payload)
        if len(_CRM_MASTER_CONFIG_CACHE) > 128:
            oldest_key = min(_CRM_MASTER_CONFIG_CACHE, key=lambda key: _CRM_MASTER_CONFIG_CACHE[key][0])
            _CRM_MASTER_CONFIG_CACHE.pop(oldest_key, None)

    def _is_transient_supabase_error(exc):
        msg = str(exc)
        return (
            'ConnectionTerminated' in msg
            or 'StreamReset' in msg
            or 'RemoteProtocolError' in msg
            or 'Server disconnected' in msg
            or 'connection reset' in msg.lower()
        )

    def _load_master_config_with_retry(sb, master_scope, include_disabled=False):
        cache_key = _master_cache_key(master_scope, include_disabled)
        cached = _master_cache_get(cache_key)
        if cached is not None:
            return cached
        last_error = None
        for attempt in range(3):
            try:
                fields = _load_master_config(sb, master_scope, include_disabled=include_disabled)
                _master_cache_set(cache_key, fields)
                return fields
            except Exception as exc:
                last_error = exc
                if not _is_transient_supabase_error(exc) or attempt >= 2:
                    raise
                time.sleep(0.2 * (attempt + 1))
        raise last_error

    def _load_master_config(sb, master_scope, include_disabled=False):
        _seed_defaults(sb, master_scope)
        is_broker = master_scope['scope'] == 'broker'
        attr_q = (
            sb.table('crm_master_attributes')
            .select('id, client_id, owner_user_id, field_key, label, is_required, is_optional, is_enabled, sort_order, applies_to')
            .order('sort_order')
        )
        values_q = (
            sb.table('crm_master_values')
            .select('id, client_id, owner_user_id, field_key, value, is_enabled, sort_order')
            .order('sort_order')
        )
        if is_broker:
            attr_q = attr_q.eq('owner_user_id', master_scope['owner_user_id']).is_('client_id', 'null')
            values_q = values_q.eq('owner_user_id', master_scope['owner_user_id']).is_('client_id', 'null')
        else:
            attr_q = attr_q.eq('client_id', master_scope['client_id']).is_('owner_user_id', 'null')
            values_q = values_q.eq('client_id', master_scope['client_id']).is_('owner_user_id', 'null')
        attr_rows = attr_q.execute().data or []
        if not include_disabled:
            values_q = values_q.eq('is_enabled', True)
        value_rows = values_q.execute().data or []
        values_by_field = {}
        for row in value_rows:
            values_by_field.setdefault(row.get('field_key'), []).append(row)
        fields = []
        for row in attr_rows:
            if not include_disabled and not row.get('is_enabled', True):
                continue
            key = row.get('field_key')
            base = field_by_key.get(key) or {'label': key or '', 'sort_order': 999}
            fields.append({
                **row,
                'label': row.get('label') or base.get('label') or key,
                'applies_to': _normalize_applies_to(row.get('applies_to'), key),
                'values': values_by_field.get(key, []),
            })
        return fields

    def _master_values_query(sb, master_scope):
        q = sb.table('crm_master_values').select('sort_order')
        if master_scope['scope'] == 'broker':
            return q.eq('owner_user_id', master_scope['owner_user_id']).is_('client_id', 'null')
        return q.eq('client_id', master_scope['client_id']).is_('owner_user_id', 'null')

    def _apply_master_scope_filter(query, master_scope):
        if master_scope['scope'] == 'broker':
            return query.eq('owner_user_id', master_scope['owner_user_id']).is_('client_id', 'null')
        return query.eq('client_id', master_scope['client_id']).is_('owner_user_id', 'null')

    def _master_field_exists(sb, master_scope, field_key):
        try:
            q = sb.table('crm_master_attributes').select('id').eq('field_key', str(field_key or '').strip()).limit(1)
            q = _apply_master_scope_filter(q, master_scope)
            rows = q.execute().data or []
            return bool(rows)
        except Exception:
            return False

    @app.route('/api/crm/master-config', methods=['GET'])
    @require_auth
    def crm_master_config(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        master_scope, err, status = _resolve_master_scope(
            sb, user_id, role,
            scope_hint=request.args.get('scope'),
            client_id_hint=request.args.get('client_id'),
            panorama_id=request.args.get('panorama_id'),
            for_write=False,
        )
        if err:
            return err, status
        try:
            include_disabled = str(request.args.get('include_disabled') or '').lower() in ('1', 'true', 'yes')
            fields = _load_master_config_with_retry(sb, master_scope, include_disabled=include_disabled)
            payload = {'scope': master_scope['scope'], 'fields': fields, 'can_manage': True}
            if master_scope['scope'] == 'broker':
                payload['owner_user_id'] = master_scope['owner_user_id']
            else:
                payload['client_id'] = master_scope['client_id']
            return jsonify(payload)
        except Exception as e:
            msg = str(e)
            if 'crm_master_' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower() or 'schema cache' in msg.lower()):
                return jsonify({'error': 'CRM master tables not found. Run db/migration_crm_broker_masters.sql in Supabase.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/crm/master-values', methods=['POST'])
    @require_auth
    def crm_master_value_create(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        master_scope, err, status = _resolve_master_scope(
            sb, user_id, role,
            scope_hint=data.get('scope'),
            client_id_hint=data.get('client_id'),
            panorama_id=data.get('panorama_id'),
            for_write=True,
        )
        if err:
            return err, status
        field_key = str(data.get('field_key') or '').strip()
        value = str(data.get('value') or '').strip()
        if not field_key:
            return jsonify({'error': 'Invalid field'}), 400
        if field_key not in field_by_key and not _master_field_exists(sb, master_scope, field_key):
            return jsonify({'error': 'Invalid field'}), 400
        if not value:
            return jsonify({'error': 'Value is required'}), 400
        if len(value) > 100:
            return jsonify({'error': 'Value must be 100 characters or less'}), 400
        try:
            _seed_defaults(sb, master_scope)
            order_rows = (
                _master_values_query(sb, master_scope)
                .eq('field_key', field_key)
                .order('sort_order', desc=True)
                .limit(1)
                .execute()
                .data or []
            )
            sort_order = int((order_rows[0] or {}).get('sort_order') or 0) + 1 if order_rows else 1
            row = {
                'field_key': field_key,
                'value': value,
                'is_enabled': True,
                'sort_order': sort_order,
                'updated_at': datetime.utcnow().isoformat(),
            }
            if master_scope['scope'] == 'broker':
                row['owner_user_id'] = master_scope['owner_user_id']
                row['client_id'] = None
            else:
                row['client_id'] = master_scope['client_id']
                row['owner_user_id'] = None
            existing = (
                _master_values_query(sb, master_scope)
                .eq('field_key', field_key)
                .eq('value', value)
                .limit(1)
                .execute()
                .data or []
            )
            if existing:
                r = sb.table('crm_master_values').update({
                    'is_enabled': True,
                    'sort_order': sort_order,
                    'updated_at': row['updated_at'],
                }).eq('id', str(existing[0].get('id'))).execute()
            else:
                r = sb.table('crm_master_values').insert(row).execute()
            crm_cache_bump()
            _CRM_MASTER_CONFIG_CACHE.clear()
            return jsonify({'success': True, 'value': (r.data or [row])[0]}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/crm/master-values/<value_id>', methods=['PATCH'])
    @require_auth
    def crm_master_value_update(user_id, role, value_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        try:
            uuid.UUID(str(value_id))
        except Exception:
            return jsonify({'error': 'Invalid value id'}), 400
        master_scope, err, status = _resolve_master_scope(
            sb, user_id, role,
            scope_hint=data.get('scope'),
            client_id_hint=data.get('client_id'),
            panorama_id=data.get('panorama_id'),
            for_write=True,
        )
        if err:
            return err, status
        upd = {'updated_at': datetime.utcnow().isoformat()}
        if 'value' in data:
            value = str(data.get('value') or '').strip()
            if not value:
                return jsonify({'error': 'Value is required'}), 400
            if len(value) > 100:
                return jsonify({'error': 'Value must be 100 characters or less'}), 400
            upd['value'] = value
        if 'is_enabled' in data:
            upd['is_enabled'] = bool(data.get('is_enabled'))
        if 'sort_order' in data:
            try:
                upd['sort_order'] = int(data.get('sort_order'))
            except Exception:
                return jsonify({'error': 'sort_order must be numeric'}), 400
        if len(upd) == 1:
            return jsonify({'error': 'Nothing to update'}), 400
        q = sb.table('crm_master_values').update(upd).eq('id', str(value_id))
        r = _apply_master_scope_filter(q, master_scope).execute()
        crm_cache_bump()
        _CRM_MASTER_CONFIG_CACHE.clear()
        return jsonify({'success': True, 'value': (r.data or [upd])[0]})

    @app.route('/api/crm/master-attributes/<field_key>', methods=['PATCH'])
    @require_auth
    def crm_master_attribute_update(user_id, role, field_key):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        master_scope, err, status = _resolve_master_scope(
            sb, user_id, role,
            scope_hint=data.get('scope'),
            client_id_hint=data.get('client_id'),
            panorama_id=data.get('panorama_id'),
            for_write=True,
        )
        if err:
            return err, status
        field_key = str(field_key or '').strip()
        if field_key not in field_by_key and not _master_field_exists(sb, master_scope, field_key):
            return jsonify({'error': 'Invalid field'}), 400
        _seed_defaults(sb, master_scope)
        upd = {'updated_at': datetime.utcnow().isoformat()}
        if 'is_required' in data or 'is_optional' in data:
            is_required = bool(data.get('is_required'))
            is_optional = bool(data.get('is_optional'))
            if is_required:
                is_optional = False
            elif is_optional:
                is_required = False
            else:
                is_optional = True
            upd['is_required'] = is_required
            upd['is_optional'] = is_optional
        if 'is_enabled' in data:
            upd['is_enabled'] = bool(data.get('is_enabled'))
        if 'label' in data:
            label = str(data.get('label') or '').strip()
            if label:
                upd['label'] = label[:100]
        if 'applies_to' in data:
            upd['applies_to'] = _normalize_applies_to(data.get('applies_to'), field_key)
        q = sb.table('crm_master_attributes').update(upd).eq('field_key', field_key)
        r = _apply_master_scope_filter(q, master_scope).execute()
        crm_cache_bump()
        _CRM_MASTER_CONFIG_CACHE.clear()
        return jsonify({'success': True, 'attribute': (r.data or [upd])[0]})

    @app.route('/api/crm/master-attributes', methods=['POST'])
    @require_auth
    def crm_master_attribute_create(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        data = request.get_json(silent=True) or {}
        master_scope, err, status = _resolve_master_scope(
            sb, user_id, role,
            scope_hint=data.get('scope'),
            client_id_hint=data.get('client_id'),
            panorama_id=data.get('panorama_id'),
            for_write=True,
        )
        if err:
            return err, status
        _seed_defaults(sb, master_scope)
        field_key = _normalize_master_field_key(data.get('field_key'))
        if not field_key:
            return jsonify({'error': 'Field key is required'}), 400
        label = str(data.get('label') or '').strip() or field_key.replace('_', ' ').title()
        applies_to = _normalize_applies_to(data.get('applies_to'), field_key)
        now = datetime.utcnow().isoformat()
        existing = (
            _apply_master_scope_filter(
                sb.table('crm_master_attributes').select('id').eq('field_key', field_key).limit(1),
                master_scope,
            ).execute().data or []
        )
        if existing:
            return jsonify({'error': 'Master already exists for this key'}), 409
        sort_rows = (
            _apply_master_scope_filter(
                sb.table('crm_master_attributes').select('sort_order').order('sort_order', desc=True).limit(1),
                master_scope,
            ).execute().data or []
        )
        sort_order = int((sort_rows[0] or {}).get('sort_order') or 0) + 10 if sort_rows else 10
        row = {
            'field_key': field_key,
            'label': label[:100],
            'is_required': bool(data.get('is_required')),
            'is_optional': not bool(data.get('is_required')),
            'is_enabled': True,
            'sort_order': sort_order,
            'applies_to': applies_to,
            'updated_at': now,
        }
        if master_scope['scope'] == 'broker':
            row['owner_user_id'] = master_scope['owner_user_id']
            row['client_id'] = None
        else:
            row['client_id'] = master_scope['client_id']
            row['owner_user_id'] = None
        created = sb.table('crm_master_attributes').insert(row).execute().data or []
        crm_cache_bump()
        _CRM_MASTER_CONFIG_CACHE.clear()
        return jsonify({'success': True, 'attribute': (created[0] if created else row)}), 201


def _crm_contact_list_select():
    return ('id, org_id, client_id, panorama_id, full_name, email, phone, birthday, address, '
            'notes, custom_fields, created_at, updated_at')


def _crm_apply_contact_list_filters(query, *, requested_client_id=None, client_scope_ids=None, q=''):
    if requested_client_id:
        query = query.eq('client_id', requested_client_id)
    elif client_scope_ids is not None:
        query = query.in_('client_id', client_scope_ids)
    token = str(q or '').strip().lower()
    if token:
        token = token.replace('%', '').replace('(', '').replace(')', '').replace(',', '')
        if token:
            query = query.or_(f"full_name.ilike.%{token}%,email.ilike.%{token}%,phone.ilike.%{token}%")
    return query


def _crm_fetch_contact_rows(
    sb,
    panorama_ids,
    *,
    client_scope_ids=None,
    requested_client_id=None,
    reference_scope_user_id=None,
    reference_contact_ids=None,
    reference_interest_ids=None,
    q='',
    offset=0,
    limit=10,
    sort_field='updated_at',
    sort_desc=True,
):
    select_cols = _crm_contact_list_select()
    rows_by_id = {}

    def add_rows(data):
        for row in (data or []):
            row_id = row.get('id')
            if row_id:
                rows_by_id[str(row_id)] = row

    if reference_scope_user_id:
        if not reference_contact_ids and not reference_interest_ids:
            return [], 0
        if reference_contact_ids:
            for chunk in _chunks(reference_contact_ids):
                query = _crm_apply_contact_list_filters(
                    sb.table('crm_contacts').select(select_cols).in_('id', chunk),
                    requested_client_id=requested_client_id,
                    client_scope_ids=client_scope_ids,
                    q=q,
                )
                add_rows(query.execute().data)
        if reference_interest_ids:
            for chunk in _chunks(reference_interest_ids):
                query = _crm_apply_contact_list_filters(
                    sb.table('crm_contacts').select(select_cols).in_('source_interest_id', chunk),
                    requested_client_id=requested_client_id,
                    client_scope_ids=client_scope_ids,
                    q=q,
                )
                add_rows(query.execute().data)
    else:
        if len(panorama_ids) <= 100:
            query = _crm_apply_contact_list_filters(
                sb.table('crm_contacts').select(select_cols, count='exact').in_('panorama_id', panorama_ids),
                requested_client_id=requested_client_id,
                client_scope_ids=client_scope_ids,
                q=q,
            )
            query = query.order(sort_field or 'updated_at', desc=bool(sort_desc))
            if (sort_field or 'updated_at') != 'updated_at':
                query = query.order('updated_at', desc=True)
            resp = query.range(offset, offset + limit - 1).execute()
            return resp.data or [], int(getattr(resp, 'count', None) or 0)
        for chunk in _chunks(panorama_ids):
            query = _crm_apply_contact_list_filters(
                sb.table('crm_contacts').select(select_cols).in_('panorama_id', chunk),
                requested_client_id=requested_client_id,
                client_scope_ids=client_scope_ids,
                q=q,
            )
            add_rows(query.execute().data)

    rows = crm_sort_rows(list(rows_by_id.values()), sort_field or 'updated_at', bool(sort_desc))
    total = len(rows)
    return rows[offset:offset + limit], total


def register_crm_contact_routes(
    app,
    *,
    crm_panorama_ids,
    crm_client_scope_ids,
    crm_interest_reference_scope_user_id,
    crm_apply_broker_referred_contact_mask,
    crm_reference_linked_ids,
    crm_cache_get,
    crm_cache_set,
    crm_cache_version,
):
    @app.route('/api/crm/contacts', methods=['GET'])
    @require_auth
    def list_crm_contacts(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        try:
            panorama_ids = with_supabase_retry(
                lambda: crm_panorama_ids(require_supabase(), user_id, role),
                attempts=3,
            )
        except Exception as e:
            if is_transient_supabase_error(e):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            return jsonify({'error': str(e) or 'Failed to load CRM panoramas'}), 503
        page, limit, offset = crm_parse_page_args(default_limit=10, max_limit=100)
        if not panorama_ids:
            return jsonify(crm_page_payload([], 0, page, limit))
        try:
            client_scope_ids = with_supabase_retry(
                lambda: crm_client_scope_ids(require_supabase(), user_id, role),
                attempts=3,
            )
        except Exception as e:
            if is_transient_supabase_error(e):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            return jsonify({'error': str(e) or 'Failed to load CRM client scope'}), 503
        if client_scope_ids is not None and not client_scope_ids:
            return jsonify(crm_page_payload([], 0, page, limit))
        try:
            reference_scope_user_id = with_supabase_retry(
                lambda: crm_interest_reference_scope_user_id(
                    require_supabase(),
                    user_id,
                    role,
                    client_scope_ids,
                ),
                attempts=3,
            )
        except Exception:
            reference_scope_user_id = None
        requested_client_id = (request.args.get('client_id') or '').strip() or None
        q = str(request.args.get('q') or '').strip().lower()
        include_counts = str(request.args.get('include_counts', '1')).strip() != '0'
        if requested_client_id and client_scope_ids is not None and requested_client_id not in client_scope_ids:
            return jsonify({'error': 'Forbidden for this client group'}), 403
        reference_interest_ids, reference_contact_ids = [], []
        if reference_scope_user_id:
            try:
                reference_interest_ids, reference_contact_ids = with_supabase_retry(
                    lambda: crm_reference_linked_ids(
                        require_supabase(),
                        reference_scope_user_id,
                        panorama_ids,
                        client_ids=client_scope_ids,
                        requested_client_id=requested_client_id,
                    ),
                    attempts=3,
                )
            except Exception:
                reference_interest_ids, reference_contact_ids = [], []
            if not reference_interest_ids and not reference_contact_ids:
                return jsonify(crm_page_payload([], 0, page, limit))
        contact_sort_field, contact_sort_desc = crm_parse_sort_args(
            CRM_CONTACT_SORT_FIELDS_MASKED if reference_scope_user_id else CRM_CONTACT_SORT_FIELDS,
            default_field='updated_at',
            default_desc=True,
        )
        cache_key = (
            'crm_contacts',
            contact_sort_field,
            contact_sort_desc,
            crm_cache_version.get('v', 1),
            str(user_id),
            str(role or ''),
            tuple(panorama_ids),
            tuple(client_scope_ids) if isinstance(client_scope_ids, list) else '__ALL__',
            reference_scope_user_id or '',
            tuple(reference_interest_ids),
            tuple(reference_contact_ids),
            requested_client_id or '',
            q,
            int(include_counts),
            page,
            limit,
            offset,
        )
        cached = crm_cache_get(cache_key, ttl_seconds=3)
        if cached is not None:
            return jsonify(cached)
        try:
            rows, total = with_supabase_retry(
                lambda: _crm_fetch_contact_rows(
                    require_supabase(),
                    panorama_ids,
                    client_scope_ids=client_scope_ids,
                    requested_client_id=requested_client_id,
                    reference_scope_user_id=reference_scope_user_id,
                    reference_contact_ids=reference_contact_ids,
                    reference_interest_ids=reference_interest_ids,
                    q=q,
                    offset=offset,
                    limit=limit,
                    sort_field=contact_sort_field,
                    sort_desc=contact_sort_desc,
                ),
                attempts=3,
            )
        except Exception as e:
            msg = str(e)
            if is_transient_supabase_error(e):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            if 'crm_contacts' in msg and ('does not exist' in msg.lower() or 'relation' in msg.lower()):
                return jsonify({'error': 'crm_contacts table not found. Run db/migration_crm_contacts_deals_quotes.sql in Supabase.'}), 503
            return jsonify({'error': msg}), 500

        contact_ids = [row.get('id') for row in rows if row.get('id')]
        deals_count = {}
        interests_count = {}
        if include_counts and contact_ids:
            try:
                dr_rows = []
                counts_sb = require_supabase()
                for chunk in _chunks(contact_ids):
                    drq = (
                        counts_sb.table('crm_deals')
                        .select('id, contact_id, interest_id')
                        .in_('contact_id', chunk)
                    )
                    if requested_client_id:
                        drq = drq.eq('client_id', requested_client_id)
                    elif client_scope_ids is not None:
                        drq = drq.in_('client_id', client_scope_ids)
                    chunk_rows = drq.execute().data or []
                    if reference_scope_user_id and reference_interest_ids:
                        allowed = {str(i) for i in reference_interest_ids}
                        chunk_rows = [d for d in chunk_rows if str(d.get('interest_id') or '') in allowed]
                    dr_rows.extend(chunk_rows)
                for d in dr_rows:
                    cid = d.get('contact_id')
                    if not cid:
                        continue
                    deals_count[cid] = deals_count.get(cid, 0) + 1
            except Exception:
                deals_count = {}
            try:
                ir_rows = []
                counts_sb = require_supabase()
                for chunk in _chunks(contact_ids):
                    irq = (
                        counts_sb.table('buy_interests')
                        .select('id, contact_id')
                        .in_('contact_id', chunk)
                    )
                    if requested_client_id:
                        irq = irq.eq('client_id', requested_client_id)
                    elif client_scope_ids is not None:
                        irq = irq.in_('client_id', client_scope_ids)
                    if reference_scope_user_id:
                        irq = irq.eq('reference_user_id', reference_scope_user_id)
                    ir_rows.extend(irq.execute().data or [])
                for irow in ir_rows:
                    cid = irow.get('contact_id')
                    if not cid:
                        continue
                    interests_count[cid] = interests_count.get(cid, 0) + 1
                if reference_scope_user_id and reference_interest_ids:
                    source_by_interest = {
                        str(row.get('source_interest_id') or ''): row.get('id')
                        for row in rows
                        if row.get('source_interest_id')
                    }
                    for iid in reference_interest_ids:
                        cid = source_by_interest.get(str(iid))
                        if cid:
                            interests_count[cid] = interests_count.get(cid, 0) + 1
            except Exception:
                interests_count = {}

        from app.services.uam_reference_service import (
            apply_broker_referred_contact_mask_to_contact,
            load_broker_refer_interest_reveal_map,
        )

        source_interest_ids = [
            str(row.get('source_interest_id') or '').strip()
            for row in rows
            if str(row.get('source_interest_id') or '').strip()
        ]
        interest_reveal_map = load_broker_refer_interest_reveal_map(sb, source_interest_ids)

        out = []
        for row in rows:
            cid = row.get('id')
            source_interest_id = str(row.get('source_interest_id') or '').strip()
            interest_row = interest_reveal_map.get(source_interest_id) or {}
            o = apply_broker_referred_contact_mask_to_contact(
                row,
                interest_row,
                user_id=user_id,
                role=role,
                reference_scope_user_id=reference_scope_user_id,
                sb=sb,
            )
            o['deals_count'] = int(deals_count.get(cid, 0))
            o['interests_count'] = int(interests_count.get(cid, 0))
            out.append(o)
        payload = crm_page_payload(out, total, page, limit)
        crm_cache_set(cache_key, payload)
        return jsonify(payload)


def register_crm_quote_routes(
    app,
    *,
    crm_panorama_ids,
    crm_client_scope_ids,
    crm_apply_client_scope,
    crm_interest_reference_scope_user_id,
    crm_reference_linked_ids,
    get_contact_for_user,
    crm_cache_bump,
):
    @app.route('/api/crm/deals/<deal_id>/quotation/share', methods=['POST'])
    @require_auth
    def share_deal_quote(user_id, role, deal_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        panorama_ids = crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return jsonify({'error': 'Forbidden'}), 403
        client_scope_ids = crm_client_scope_ids(sb, user_id, role)
        # Brokers may only share quotes on their own referred deals; without
        # this they could mail another broker's contact details to any address.
        reference_scope_user_id = crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        reference_interest_ids = []
        if reference_scope_user_id:
            reference_interest_ids, _reference_contact_ids = crm_reference_linked_ids(
                sb,
                reference_scope_user_id,
                panorama_ids,
                client_ids=client_scope_ids,
            )
            if not reference_interest_ids:
                return jsonify({'error': 'Deal not found or access denied'}), 404
        data = request.get_json(silent=True) or {}
        quote_id = str(data.get('quote_id') or '').strip()
        if not quote_id:
            return jsonify({'error': 'quote_id is required'}), 400
        qr = (
            sb.table('crm_deal_quotes')
            .select('id, deal_id, contact_id, quote_payload, share_token')
            .eq('id', quote_id)
            .eq('deal_id', str(deal_id))
            .limit(1)
            .execute()
        )
        if not qr.data:
            return jsonify({'error': 'Quote not found'}), 404
        quote = qr.data[0]
        drq = (
            sb.table('crm_deals')
            .select('id, panorama_id, title')
            .eq('id', str(deal_id))
        )
        drq = drq.in_('panorama_id', panorama_ids)
        if client_scope_ids is not None:
            drq = crm_apply_client_scope(drq, client_scope_ids)
            if drq is None:
                return jsonify({'error': 'Deal not found or access denied'}), 404
        if reference_scope_user_id:
            drq = drq.in_('interest_id', reference_interest_ids)
        dr = drq.limit(1).execute()
        if not dr.data:
            return jsonify({'error': 'Deal not found or access denied'}), 404
        to_email = str(data.get('email') or '').strip()[:254]
        to_phone = str(data.get('phone') or '').strip()[:32]
        if to_email and ('@' not in to_email or ' ' in to_email):
            return jsonify({'error': 'Invalid recipient email'}), 400
        if not to_email and quote.get('contact_id'):
            contact = get_contact_for_user(sb, quote.get('contact_id'), panorama_ids, client_ids=client_scope_ids)
            if contact:
                to_email = str(contact.get('email') or '').strip()
                to_phone = str(contact.get('phone') or '').strip()
        if not to_email:
            return jsonify({'error': 'No recipient email found'}), 400
        share_url = f"{request.url_root.rstrip('/')}/api/crm/deals/{deal_id}/quotation/{quote_id}?token={quote.get('share_token')}"
        subject = f"Quotation for {dr.data[0].get('title') or 'your deal'}"
        body = (
            f"Hello,\n\nPlease review your quotation using the link below:\n{share_url}\n\n"
            f"Shared via MarketoState CRM on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}.\n"
        )
        try:
            send_smtp_email(
                smtp_host=app_config.SMTP_HOST,
                smtp_port=app_config.SMTP_PORT,
                smtp_username=app_config.SMTP_USERNAME,
                smtp_password=app_config.SMTP_PASSWORD,
                smtp_use_tls=app_config.SMTP_USE_TLS,
                from_email=app_config.SMTP_FROM_EMAIL,
                from_name=app_config.SMTP_FROM_NAME,
                to_email=to_email,
                subject=subject,
                text_body=body,
            )
        except Exception as e:
            return jsonify({'error': f'Email send failed: {e}'}), 500
        now = datetime.utcnow().isoformat()
        sb.table('crm_deal_quotes').update({
            'sent_to_email': to_email,
            'sent_to_phone': to_phone,
            'shared_via': 'email',
            'sent_at': now,
            'updated_at': now,
            'status': 'sent',
        }).eq('id', quote_id).execute()
        crm_cache_bump()
        return jsonify({'success': True, 'share_url': share_url})
