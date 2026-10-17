"""
Unified CRM record listing.

One handler serves every tab of the CRM from the single crm_leads table:

  GET /api/crm/leads?status=interest|deal|all   canonical
  GET /api/buy-interests                        alias: status=interest
  GET /api/crm/deals                            alias: status=deal
  GET /api/crm/contacts                         alias: status=deal (contacts are deals)

Response: {items, total, page, limit, pages, filter_options}
"""
import json
import re

from flask import jsonify, request

from app.controllers.features.crm_pagination import (
    crm_page_payload,
    crm_parse_page_args,
    crm_parse_sort_args,
)
from app.core.auth import require_auth
from app.core.database import (
    get_supabase,
    is_transient_supabase_error,
    require_supabase,
    with_supabase_retry,
)
from app.services import crm_lead_service as leads

FACET_ROW_CAP = 5000
KANBAN_MAX_LIMIT = 500

# ---------------------------------------------------------------------------
# Operator filters (?filters=[{"field","op","value","value2"}] , ANDed)
# ---------------------------------------------------------------------------
MAX_FILTER_CONDITIONS = 20
MAX_FILTER_VALUE_LEN = 200

FILTER_TEXT_COLUMNS = {
    'customer_name': 'customer_name', 'customer_email': 'customer_email', 'customer_phone': 'customer_phone',
    'customer_city': 'customer_city', 'customer_state': 'customer_state', 'customer_country': 'customer_country',
    'customer_zip_code': 'customer_zip_code', 'customer_address': 'customer_address', 'title': 'title',
    'category': 'category', 'lead_source': 'lead_source', 'lead_category': 'lead_category',
    'lead_status': 'lead_status', 'campaign_type': 'campaign_type', 'campaign_status': 'campaign_status',
    'description': 'description', 'notes': 'notes', 'deal_title': 'deal_title', 'deal_amount': 'deal_amount',
    'deal_project_name': 'deal_project_name', 'deal_currency': 'deal_currency',
}
FILTER_SELECT_COLUMNS = {
    'client_id': 'client_id', 'reference_user_id': 'reference_user_id',
    'reference_user_role': 'reference_user_role', 'deal_stage': 'deal_stage', 'panorama_id': 'panorama_id',
}
# 'ts' columns are timestamptz, 'date' columns are plain dates.
FILTER_DATE_COLUMNS = {
    'created_at': 'ts', 'updated_at': 'ts', 'converted_at': 'ts', 'contact_revealed_at': 'ts',
    'customer_birthday': 'date',
}
TEXT_OPS = ('is', 'isnt', 'contains', 'not_contains', 'starts_with', 'ends_with', 'empty', 'not_empty')
SELECT_OPS = ('is', 'isnt', 'empty', 'not_empty')
DATE_OPS = ('on', 'after', 'before', 'between', 'empty', 'not_empty')
PLOT_OPS = ('is', 'isnt', 'empty', 'not_empty')
NO_VALUE_OPS = ('empty', 'not_empty')
_CUSTOM_KEY_RE = re.compile(r'^[a-z0-9_]{1,64}$')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class FilterError(ValueError):
    pass


def _like_escape(value):
    """Escape LIKE metacharacters so user text is matched literally."""
    text = str(value or '')[:MAX_FILTER_VALUE_LEN]
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_').replace('*', '')


def _filter_kind(field):
    if field in FILTER_TEXT_COLUMNS:
        return 'text', FILTER_TEXT_COLUMNS[field]
    if field in FILTER_SELECT_COLUMNS:
        return 'select', FILTER_SELECT_COLUMNS[field]
    if field in FILTER_DATE_COLUMNS:
        return 'date', field
    if field == 'workspace_id':
        return 'workspace', None
    if field == 'plot_id':
        return 'plot', 'plots'
    if field.startswith('cf.'):
        key = field[3:]
        if _CUSTOM_KEY_RE.match(key):
            return 'text', f'custom_fields->>{key}'
    return None, None


def parse_filter_conditions(raw):
    """Validate the client-sent filter list. Raises FilterError on bad input."""
    raw = str(raw or '').strip()
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except Exception:
        raise FilterError('filters must be a JSON array')
    if not isinstance(items, list):
        raise FilterError('filters must be a JSON array')
    if len(items) > MAX_FILTER_CONDITIONS:
        raise FilterError(f'At most {MAX_FILTER_CONDITIONS} filter conditions are allowed')
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        field = str(item.get('field') or '').strip()
        op = str(item.get('op') or '').strip().lower()
        kind, column = _filter_kind(field)
        if not kind:
            raise FilterError(f'Unknown filter field: {field}')
        allowed = {'text': TEXT_OPS, 'select': SELECT_OPS, 'date': DATE_OPS, 'workspace': SELECT_OPS, 'plot': PLOT_OPS}[kind]
        if op not in allowed:
            raise FilterError(f'Operator "{op}" is not valid for {field}')
        value = str(item.get('value') if item.get('value') is not None else '').strip()[:MAX_FILTER_VALUE_LEN]
        value2 = str(item.get('value2') if item.get('value2') is not None else '').strip()[:MAX_FILTER_VALUE_LEN]
        if op not in NO_VALUE_OPS and not value:
            continue  # incomplete condition: ignore rather than fail the whole request
        if kind == 'date' and op not in NO_VALUE_OPS:
            if not _DATE_RE.match(value) or (op == 'between' and not _DATE_RE.match(value2)):
                raise FilterError(f'{field} filter needs YYYY-MM-DD dates')
        if field == 'deal_stage' and op in ('is', 'isnt'):
            value = leads.normalize_deal_stage(value) or ''
            if not value:
                raise FilterError('Unknown deal stage')
        if field in ('panorama_id', 'plot_id') and op in ('is', 'isnt'):
            try:
                value = str(int(value))
            except Exception:
                raise FilterError(f'{field} must be numeric')
        out.append({'field': field, 'op': op, 'value': value, 'value2': value2, 'kind': kind, 'column': column})
    return out


def _date_bounds(value, mode):
    if mode == 'date':
        return value, value
    return value + 'T00:00:00', value + 'T23:59:59.999999'


def apply_filter_conditions(query, conditions, *, scope, active_sb):
    """Apply validated conditions to a crm_leads query. Returns None when a
    condition can never match (e.g. a project with no visible panoramas)."""
    for cond in conditions:
        kind, col, op, value, value2 = cond['kind'], cond['column'], cond['op'], cond['value'], cond['value2']
        if op == 'empty':
            if kind == 'plot':
                query = query.eq('plots', '[]')
            elif kind == 'workspace':
                continue
            else:
                query = query.or_(f'{col}.is.null,{col}.eq.')
            continue
        if op == 'not_empty':
            if kind == 'plot':
                query = query.neq('plots', '[]')
            elif kind == 'workspace':
                continue
            elif kind == 'date':
                query = query.not_.is_(col, 'null')
            else:
                query = query.neq(col, '')  # NULL rows fail <> too
            continue
        if kind == 'text':
            v = _like_escape(value)
            if op == 'is':
                query = query.ilike(col, v)
            elif op == 'isnt':
                query = query.not_.ilike(col, v)
            elif op == 'contains':
                query = query.ilike(col, f'%{v}%')
            elif op == 'not_contains':
                query = query.not_.ilike(col, f'%{v}%')
            elif op == 'starts_with':
                query = query.ilike(col, f'{v}%')
            elif op == 'ends_with':
                query = query.ilike(col, f'%{v}')
        elif kind == 'select':
            if col == 'client_id' and scope.get('client_scope_ids') is not None and value not in scope['client_scope_ids']:
                return None
            query = query.eq(col, value) if op == 'is' else query.neq(col, value)
        elif kind == 'date':
            start, end = _date_bounds(value, FILTER_DATE_COLUMNS[col])
            if op == 'on':
                query = query.gte(col, start).lte(col, end)
            elif op == 'after':
                query = query.gt(col, end)
            elif op == 'before':
                query = query.lt(col, start)
            elif op == 'between':
                _s2, end2 = _date_bounds(value2, FILTER_DATE_COLUMNS[col])
                lo, hi = (start, end2) if start <= end2 else (_date_bounds(value2, FILTER_DATE_COLUMNS[col])[0], end)
                query = query.gte(col, lo).lte(col, hi)
        elif kind == 'plot':
            payload = json.dumps([{'plot_id': int(value)}])
            query = query.contains('plots', payload) if op == 'is' else query.not_.contains('plots', payload)
        elif kind == 'workspace':
            rows = (
                active_sb.table('panoramas').select('id').eq('workspace_id', value)
                .in_('id', scope['panorama_ids']).execute().data or []
            )
            ids = [int(r.get('id')) for r in rows if r.get('id') is not None]
            if op == 'is':
                if not ids:
                    return None
                query = query.in_('panorama_id', ids)
            elif ids:
                query = query.not_.in_('panorama_id', ids)
    return query


def _sanitize_search_token(raw):
    """Strip PostgREST filter metacharacters before interpolating into or_()."""
    return (
        str(raw or '')
        .replace('%', '')
        .replace('(', '')
        .replace(')', '')
        .replace(',', '')
        .replace('.', ' ')
        .strip()
    )


def _lead_facets(sb, *, scope, status, crm_cache_get, crm_cache_set, crm_cache_version, user_id, role):
    """Dropdown options for the filter rail: only values that exist in the
    caller's visible scope for this status. Ignores the active filters so
    picking one option never removes the others."""
    cache_key = (
        'crm_lead_facets',
        crm_cache_version.get('v', 1),
        str(user_id),
        str(role or ''),
        tuple(scope['panorama_ids']),
        tuple(scope['client_scope_ids']) if isinstance(scope.get('client_scope_ids'), list) else '__ALL__',
        scope.get('reference_scope_user_id') or '',
        status or 'all',
    )
    cached = crm_cache_get(cache_key, ttl_seconds=8)
    if cached is not None:
        return cached
    rows = []
    try:
        query = (
            sb.table(leads.LEAD_TABLE)
            .select('client_id, panorama_id, category, lead_source, lead_category, lead_status, campaign_type, campaign_status, deal_stage, reference_user_id, reference_user_role, record_status, plots')
        )
        query = leads.apply_record_scope(query, scope)
        if status in leads.LEAD_STATUSES:
            query = query.eq('record_status', status)
        rows = query.order('created_at', desc=True).range(0, FACET_ROW_CAP - 1).execute().data or []
    except Exception:
        rows = []

    client_ids = sorted({str(r.get('client_id')) for r in rows if r.get('client_id')})
    pano_ids = sorted({int(r.get('panorama_id')) for r in rows if r.get('panorama_id') is not None})
    ref_ids = sorted({str(r.get('reference_user_id')) for r in rows if r.get('reference_user_id')})
    cnames = leads.client_name_map(sb, client_ids)
    pmap = leads.panorama_info_map(sb, pano_ids)
    pnames = leads.profile_name_map(sb, ref_ids)

    workspaces = {}
    panoramas = []
    for pid in pano_ids:
        info = pmap.get(pid) or {}
        wsid = info.get('workspace_id')
        if wsid and wsid not in workspaces:
            workspaces[wsid] = info.get('workspace_name') or ('Project #' + str(wsid)[:8])
        panoramas.append({'id': pid, 'name': info.get('name') or f'Panorama #{pid}', 'workspace_id': wsid})
    categories = sorted({str(r.get('category') or '').strip() for r in rows if str(r.get('category') or '').strip()}, key=str.lower)
    lead_sources = sorted({str(r.get('lead_source') or '').strip() for r in rows if str(r.get('lead_source') or '').strip()}, key=str.lower)
    def _distinct(col):
        return sorted({str(r.get(col) or '').strip() for r in rows if str(r.get(col) or '').strip()}, key=str.lower)
    lead_categories = _distinct('lead_category')
    lead_statuses = _distinct('lead_status')
    campaign_types = _distinct('campaign_type')
    campaign_statuses = _distinct('campaign_status')
    stage_counts = {}
    for r in rows:
        if str(r.get('record_status') or '') != leads.STATUS_DEAL:
            continue
        st = str(r.get('deal_stage') or 'new')
        stage_counts[st] = stage_counts.get(st, 0) + 1
    ref_roles = {}
    references = {}
    for r in rows:
        uid = str(r.get('reference_user_id') or '')
        if not uid:
            continue
        role_key = str(r.get('reference_user_role') or '').strip()
        if uid not in references:
            references[uid] = {
                'id': uid,
                'name': pnames.get(uid) or uid[:8] + '…',
                'role': role_key,
                'role_label': leads.role_label(role_key) if role_key else '',
            }
        if role_key and role_key not in ref_roles:
            ref_roles[role_key] = leads.role_label(role_key)
    plots = {}
    for r in rows:
        for p in (r.get('plots') or []):
            if not isinstance(p, dict):
                continue
            pid = p.get('plot_id') if p.get('plot_id') is not None else p.get('id')
            if pid is None or str(pid).strip() == '':
                continue
            key = str(pid)
            if key not in plots:
                plots[key] = {'id': key, 'name': str(p.get('name') or '').strip() or ('Plot #' + key)}
        if len(plots) >= 400:
            break

    out = {
        'clients': sorted(
            [{'id': cid, 'name': cnames.get(cid) or cid} for cid in client_ids],
            key=lambda x: str(x['name']).lower(),
        ),
        'workspaces': sorted(
            [{'id': wsid, 'name': name} for wsid, name in workspaces.items()],
            key=lambda x: str(x['name']).lower(),
        ),
        'panoramas': sorted(panoramas, key=lambda x: str(x['name']).lower()),
        'plots': sorted(plots.values(), key=lambda x: str(x['name']).lower()),
        'categories': categories,
        'lead_sources': lead_sources,
        'lead_categories': lead_categories,
        'lead_statuses': lead_statuses,
        'campaign_types': campaign_types,
        'campaign_statuses': campaign_statuses,
        'stages': [
            {'key': st, 'label': leads.DEAL_STAGE_LABELS.get(st, st), 'count': int(stage_counts.get(st, 0))}
            for st in leads.DEAL_STAGES
        ],
        'references': sorted(references.values(), key=lambda x: str(x['name']).lower()),
        'reference_roles': [{'key': k, 'label': v} for k, v in ref_roles.items()],
        'total_in_scope': len(rows),
    }
    crm_cache_set(cache_key, out)
    return out


def register_crm_record_list_routes(
    app,
    *,
    crm_panorama_ids,
    crm_client_scope_ids,
    crm_interest_reference_scope_user_id,
    crm_cache_get,
    crm_cache_set,
    crm_cache_version,
):
    def _list_leads(user_id, role, forced_status=None):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        page, limit, offset = crm_parse_page_args(default_limit=10, max_limit=KANBAN_MAX_LIMIT)
        status = forced_status or str(request.args.get('status') or 'all').strip().lower()
        if status not in leads.LEAD_STATUSES:
            status = 'all'
        empty = crm_page_payload([], 0, page, limit)
        empty['filter_options'] = None
        try:
            panorama_ids = with_supabase_retry(lambda: crm_panorama_ids(require_supabase(), user_id, role), attempts=3)
        except Exception as error:
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            return jsonify({'error': str(error)}), 500
        if not panorama_ids:
            return jsonify(empty)
        try:
            client_scope_ids = with_supabase_retry(lambda: crm_client_scope_ids(require_supabase(), user_id, role), attempts=3)
        except Exception as error:
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            return jsonify({'error': str(error)}), 500
        if client_scope_ids is not None and not client_scope_ids:
            return jsonify(empty)
        try:
            reference_scope_user_id = with_supabase_retry(
                lambda: crm_interest_reference_scope_user_id(require_supabase(), user_id, role, client_scope_ids),
                attempts=3,
            )
        except Exception as error:
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            return jsonify({'error': str(error)}), 500
        caps = leads.get_user_caps(sb, user_id, role)
        scope = {
            'panorama_ids': [int(p) for p in panorama_ids],
            'client_scope_ids': client_scope_ids,
            'reference_scope_user_id': reference_scope_user_id,
            'caps': caps,
        }

        args = request.args
        requested_client_id = (args.get('client_id') or '').strip() or None
        if requested_client_id and client_scope_ids is not None and requested_client_id not in client_scope_ids:
            return jsonify({'error': 'Forbidden for this client group'}), 403
        workspace_id = (args.get('workspace_id') or '').strip() or None
        try:
            panorama_id = int(args.get('panorama_id')) if str(args.get('panorama_id') or '').strip() else None
        except Exception:
            panorama_id = None
        try:
            plot_id = int(args.get('plot_id')) if str(args.get('plot_id') or '').strip() else None
        except Exception:
            plot_id = None
        category = (args.get('category') or '').strip() or None
        lead_source = (args.get('lead_source') or '').strip() or None
        reference_user_id = (args.get('reference_user_id') or '').strip() or None
        reference_role = (args.get('reference_role') or '').strip().lower() or None
        deal_stage = leads.normalize_deal_stage(args.get('deal_stage') or args.get('stage'))
        search_query = (args.get('q') or '').strip()
        include_facets = str(args.get('include_facets', '1')).strip() != '0'
        filters_raw = (args.get('filters') or '').strip()
        try:
            conditions = parse_filter_conditions(filters_raw)
        except FilterError as error:
            return jsonify({'error': str(error), 'field': 'filters'}), 400
        # Masked viewers (brokers on shared scope) cannot order by hidden columns.
        sort_field, sort_desc = crm_parse_sort_args(
            leads.LEAD_SORT_FIELDS_MASKED if reference_scope_user_id else leads.LEAD_SORT_FIELDS,
            default_field='created_at',
            default_desc=True,
        )

        cache_key = (
            'crm_leads_list',
            crm_cache_version.get('v', 1),
            str(user_id),
            str(role or ''),
            tuple(scope['panorama_ids']),
            tuple(client_scope_ids) if isinstance(client_scope_ids, list) else '__ALL__',
            reference_scope_user_id or '',
            status,
            requested_client_id or '',
            workspace_id or '',
            panorama_id or 0,
            plot_id or 0,
            category or '',
            lead_source or '',
            reference_user_id or '',
            reference_role or '',
            deal_stage or '',
            search_query.lower(),
            filters_raw,
            sort_field,
            sort_desc,
            int(include_facets),
            page,
            limit,
        )
        cached = crm_cache_get(cache_key, ttl_seconds=3)
        if cached is not None:
            return jsonify(cached)

        try:
            def _fetch_page():
                active_sb = require_supabase()
                query = active_sb.table(leads.LEAD_TABLE).select(leads.LEAD_SELECT_COLUMNS, count='exact')
                query = leads.apply_record_scope(query, scope, requested_client_id=requested_client_id)
                if status in leads.LEAD_STATUSES:
                    query = query.eq('record_status', status)
                if workspace_id:
                    ws_rows = (
                        active_sb.table('panoramas')
                        .select('id')
                        .eq('workspace_id', workspace_id)
                        .in_('id', scope['panorama_ids'])
                        .execute()
                        .data or []
                    )
                    ws_pano_ids = [int(r.get('id')) for r in ws_rows if r.get('id') is not None]
                    if not ws_pano_ids:
                        return None
                    query = query.in_('panorama_id', ws_pano_ids)
                if panorama_id and panorama_id in scope['panorama_ids']:
                    query = query.eq('panorama_id', panorama_id)
                if plot_id is not None:
                    # jsonb @> : postgrest-py only json-encodes dicts, so pass the array as a string.
                    query = query.contains('plots', json.dumps([{'plot_id': plot_id}]))
                if category:
                    query = query.eq('category', category)
                if lead_source:
                    query = query.eq('lead_source', lead_source)
                if reference_user_id:
                    query = query.eq('reference_user_id', reference_user_id)
                if reference_role:
                    query = query.eq('reference_user_role', reference_role)
                if deal_stage:
                    query = query.eq('deal_stage', deal_stage)
                if conditions:
                    query = apply_filter_conditions(query, conditions, scope=scope, active_sb=active_sb)
                    if query is None:
                        return None
                if search_query:
                    token = _sanitize_search_token(search_query)
                    if token:
                        query = query.or_(
                            f"customer_name.ilike.%{token}%,customer_email.ilike.%{token}%,"
                            f"customer_phone.ilike.%{token}%,deal_title.ilike.%{token}%,"
                            f"category.ilike.%{token}%,customer_city.ilike.%{token}%,"
                            f"deal_project_name.ilike.%{token}%,notes.ilike.%{token}%"
                        )
                query = query.order(sort_field, desc=sort_desc)
                if sort_field != 'created_at':
                    query = query.order('created_at', desc=True)
                return query.range(offset, offset + limit - 1).execute()

            response = with_supabase_retry(_fetch_page, attempts=3)
            facets = None
            if include_facets:
                facets = _lead_facets(
                    sb, scope=scope, status=status,
                    crm_cache_get=crm_cache_get, crm_cache_set=crm_cache_set, crm_cache_version=crm_cache_version,
                    user_id=user_id, role=role,
                )
            if response is None:
                payload = crm_page_payload([], 0, page, limit)
                payload['filter_options'] = facets
                crm_cache_set(cache_key, payload)
                return jsonify(payload)
            total = int(getattr(response, 'count', None) or 0)
            rows = leads.shape_lead_rows(
                sb, response.data or [],
                user_id=user_id, role=role, reference_scope_user_id=reference_scope_user_id, caps=caps,
            )
            payload = crm_page_payload(rows, total, page, limit)
            payload['filter_options'] = facets
            payload['status'] = status
            payload['caps'] = {
                'can_manage_deals': bool(caps.get('can_manage_deals')),
                'is_broker': bool(caps.get('is_broker')),
                'is_platform_admin': bool(caps.get('is_platform_admin')),
            }
            crm_cache_set(cache_key, payload)
            return jsonify(payload)
        except Exception as error:
            message = str(error)
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            if 'crm_leads' in message and ('does not exist' in message.lower() or 'relation' in message.lower() or 'schema cache' in message.lower()):
                return jsonify({'error': 'crm_leads table not found. Run db/migration_crm_unified_leads.sql in Supabase.'}), 503
            return jsonify({'error': message}), 500

    @app.route('/api/crm/leads', methods=['GET'])
    @require_auth
    def list_crm_leads(user_id, role):
        return _list_leads(user_id, role)

    @app.route('/api/buy-interests', methods=['GET'])
    @require_auth
    def list_buy_interests(user_id, role):
        return _list_leads(user_id, role, leads.STATUS_INTEREST)

    @app.route('/api/crm/deals', methods=['GET'])
    @require_auth
    def list_crm_deals(user_id, role):
        return _list_leads(user_id, role, leads.STATUS_DEAL)

    @app.route('/api/crm/contacts', methods=['GET'])
    @require_auth
    def list_crm_contacts(user_id, role):
        return _list_leads(user_id, role, leads.STATUS_DEAL)
