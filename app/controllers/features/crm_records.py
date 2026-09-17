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

# Contact columns are masked for reference-scoped brokers, so ordering by them
# would leak values those users are not allowed to see.
BUY_INTEREST_SORT_FIELDS = (
    'created_at', 'customer_name', 'customer_email', 'customer_phone', 'category',
)
BUY_INTEREST_SORT_FIELDS_MASKED = ('created_at', 'customer_name', 'category')
# 'amount' is a free-text column: a database sort on it would order money
# lexicographically, so it is deliberately not sortable.
CRM_DEAL_SORT_FIELDS = ('title', 'stage', 'project_name', 'updated_at')


def _crm_deals_client_facet(
    sb,
    *,
    panorama_ids,
    client_scope_ids,
    reference_scope_user_id,
    reference_interest_ids,
    crm_cache_get,
    crm_cache_set,
    crm_cache_version,
    user_id,
    role,
):
    """Client dropdown options for the Deals filter: only clients that
    actually have a deal row in the caller's visible scope, not every client
    group the caller can access. Ignores the currently-selected client_id
    filter (and stage/project/contact/search) so picking one option never
    removes the others from the dropdown.
    """
    cache_key = (
        'crm_deals_client_facet',
        crm_cache_version.get('v', 1),
        str(user_id),
        str(role or ''),
        tuple(panorama_ids),
        tuple(client_scope_ids) if isinstance(client_scope_ids, list) else '__ALL__',
        reference_scope_user_id or '',
        tuple(reference_interest_ids or ()),
    )
    cached = crm_cache_get(cache_key, ttl_seconds=5)
    if cached is not None:
        return cached
    if client_scope_ids is not None and not client_scope_ids:
        crm_cache_set(cache_key, [])
        return []
    try:
        query = sb.table('crm_deals').select('client_id').in_('panorama_id', panorama_ids)
        if client_scope_ids is not None:
            query = query.in_('client_id', client_scope_ids)
        if reference_scope_user_id:
            query = query.in_('interest_id', reference_interest_ids or [])
        rows = query.execute().data or []
    except Exception:
        rows = []
    client_ids = sorted({str(row.get('client_id')) for row in rows if row.get('client_id')})
    if not client_ids:
        crm_cache_set(cache_key, [])
        return []
    names = {}
    try:
        name_rows = sb.table('clients').select('id, name').in_('id', client_ids).execute().data or []
        for row in name_rows:
            cid = str(row.get('id') or '')
            if cid:
                names[cid] = str(row.get('name') or '').strip() or cid
    except Exception:
        pass
    out = [{'id': cid, 'name': names.get(cid) or cid} for cid in client_ids]
    out.sort(key=lambda item: str(item.get('name') or '').lower())
    crm_cache_set(cache_key, out)
    return out


def _apply_client_scope(query, *, requested_client_id=None, client_scope_ids=None):
    if requested_client_id:
        return query.eq('client_id', requested_client_id)
    if client_scope_ids is not None:
        return query.in_('client_id', client_scope_ids)
    return query


def _attach_reference_user_names(sb, rows):
    if not rows:
        return rows
    ref_ids = []
    seen = set()
    for row in rows:
        ref_uid = str(row.get('reference_user_id') or '').strip()
        if ref_uid and ref_uid not in seen:
            seen.add(ref_uid)
            ref_ids.append(ref_uid)
    profile_map = {}
    chunk_size = 100
    for index in range(0, len(ref_ids), chunk_size):
        chunk = ref_ids[index:index + chunk_size]
        try:
            response = (
                sb.table('profiles')
                .select('user_id, display_name, email')
                .in_('user_id', chunk)
                .execute()
            )
            for profile in (response.data or []):
                uid = str(profile.get('user_id') or '').strip()
                if not uid:
                    continue
                profile_map[uid] = str(profile.get('display_name') or profile.get('email') or '').strip()
        except Exception:
            pass
    for row in rows:
        ref_uid = str(row.get('reference_user_id') or '').strip()
        row['reference_user_name'] = profile_map.get(ref_uid, '')
    return rows


def register_crm_record_list_routes(
    app,
    *,
    crm_panorama_ids,
    crm_client_scope_ids,
    crm_interest_reference_scope_user_id,
    crm_apply_broker_interest_visibility,
    crm_apply_broker_referred_contact_mask,
    crm_reference_linked_ids,
    crm_cache_get,
    crm_cache_set,
    crm_cache_version,
):
    @app.route('/api/buy-interests', methods=['GET'])
    @require_auth
    def list_buy_interests(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        page, limit, offset = crm_parse_page_args(default_limit=10, max_limit=500)
        try:
            panorama_ids = with_supabase_retry(
                lambda: crm_panorama_ids(require_supabase(), user_id, role),
                attempts=3,
            )
        except Exception as error:
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            return jsonify({'error': str(error)}), 500
        if not panorama_ids:
            return jsonify(crm_page_payload([], 0, page, limit))
        try:
            client_scope_ids = with_supabase_retry(
                lambda: crm_client_scope_ids(require_supabase(), user_id, role),
                attempts=3,
            )
        except Exception as error:
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            return jsonify({'error': str(error)}), 500
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
        except Exception as error:
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            return jsonify({'error': str(error)}), 500

        panorama_id = request.args.get('panorama_id')
        workspace_id = (request.args.get('workspace_id') or '').strip() or None
        category = (request.args.get('category') or '').strip() or None
        requested_client_id = (request.args.get('client_id') or '').strip() or None
        status = (request.args.get('status') or '').strip().lower()
        search_query = (request.args.get('q') or '').strip()
        try:
            panorama_id = int(panorama_id) if str(panorama_id or '').strip() else None
        except Exception:
            panorama_id = None
        if requested_client_id and client_scope_ids is not None and requested_client_id not in client_scope_ids:
            return jsonify({'error': 'Forbidden for this client group'}), 403

        sort_field, sort_desc = crm_parse_sort_args(
            BUY_INTEREST_SORT_FIELDS_MASKED if reference_scope_user_id else BUY_INTEREST_SORT_FIELDS,
            default_field='created_at',
            default_desc=True,
        )
        cache_key = (
            'buy_interests',
            sort_field,
            sort_desc,
            crm_cache_version.get('v', 1),
            str(user_id),
            str(role or ''),
            tuple(panorama_ids),
            tuple(client_scope_ids) if isinstance(client_scope_ids, list) else '__ALL__',
            reference_scope_user_id or '',
            requested_client_id or '',
            panorama_id or 0,
            workspace_id or '',
            category or '',
            status,
            search_query.lower(),
            page,
            limit,
            offset,
        )
        cached = crm_cache_get(cache_key, ttl_seconds=3)
        if cached is not None:
            return jsonify(cached)

        try:
            columns = (
                'id, client_id, panorama_id, contact_id, reference_user_id, contact_revealed_at, customer_name, '
                'customer_email, customer_phone, customer_birthday, customer_address, customer_street, customer_city, '
                'customer_state, customer_country, customer_zip_code, lead_source, lead_category, lead_status, '
                'campaign_type, campaign_status, deal_stage, title, description, category, plots, status, is_contacted, '
                'contacted_at, notes, custom_fields, created_at, updated_at, submitted_by, assigned_to, assigned_at'
            )

            def _fetch_buy_interests_page():
                active_sb = require_supabase()
                query = active_sb.table('buy_interests').select(columns, count='exact').in_('panorama_id', panorama_ids)
                query = _apply_client_scope(
                    query,
                    requested_client_id=requested_client_id,
                    client_scope_ids=client_scope_ids,
                )
                if reference_scope_user_id:
                    query = crm_apply_broker_interest_visibility(query, reference_scope_user_id)
                if workspace_id:
                    workspace_rows = (
                        active_sb.table('panoramas')
                        .select('id')
                        .eq('workspace_id', workspace_id)
                        .in_('id', panorama_ids)
                        .execute()
                        .data
                        or []
                    )
                    workspace_panorama_ids = [
                        int(row.get('id'))
                        for row in workspace_rows
                        if row.get('id') is not None
                    ]
                    if not workspace_panorama_ids:
                        return None
                    query = query.in_('panorama_id', workspace_panorama_ids)
                if panorama_id and panorama_id in panorama_ids:
                    query = query.eq('panorama_id', panorama_id)
                if category:
                    query = query.eq('category', category)
                if status in ('new', 'contacted'):
                    query = query.eq('is_contacted', status == 'contacted')
                if search_query:
                    token = search_query.replace('%', '').replace('(', '').replace(')', '').replace(',', '')
                    if token:
                        query = query.or_(
                            f"customer_name.ilike.%{token}%,customer_email.ilike.%{token}%,"
                            f"customer_phone.ilike.%{token}%,customer_address.ilike.%{token}%,"
                            f"customer_city.ilike.%{token}%,customer_state.ilike.%{token}%"
                        )
                query = query.order(sort_field, desc=sort_desc)
                if sort_field != 'created_at':
                    query = query.order('created_at', desc=True)
                return query.range(offset, offset + limit - 1).execute()

            response = with_supabase_retry(_fetch_buy_interests_page, attempts=3)
            if response is None:
                return jsonify(crm_page_payload([], 0, page, limit))
            total = int(getattr(response, 'count', None) or 0)
            rows = []
            for row in (response.data or []):
                item = dict(row)
                for key in ('created_at', 'updated_at'):
                    if item.get(key):
                        item[key] = str(item[key])
                if item.get('contacted_at'):
                    item['contacted_at'] = str(item['contacted_at'])
                legacy_status = str(item.get('status') or '').strip().lower()
                legacy_contacted = legacy_status in ('contacted', 'qualified', 'won', 'lost')
                item['is_contacted'] = bool(item.get('is_contacted') or legacy_contacted)
                if item['is_contacted'] and not item.get('contacted_at'):
                    item['contacted_at'] = item.get('updated_at') or item.get('created_at')
                for key in ('submitted_by', 'contact_id', 'reference_user_id', 'assigned_to', 'assigned_at'):
                    if item.get(key):
                        item[key] = str(item[key])
                item = crm_apply_broker_referred_contact_mask(
                    item,
                    user_id=user_id,
                    role=role,
                    reference_scope_user_id=reference_scope_user_id,
                    sb=sb,
                )
                rows.append(item)
            rows = _attach_reference_user_names(sb, rows)
            payload = crm_page_payload(rows, total, page, limit)
            crm_cache_set(cache_key, payload)
            return jsonify(payload)
        except Exception as error:
            message = str(error)
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            if 'buy_interests' in message and (
                'does not exist' in message.lower() or 'relation' in message.lower()
            ):
                return jsonify({
                    'error': 'buy_interests table not found. Run db/schema.sql in Supabase SQL Editor.'
                }), 503
            return jsonify({'error': message}), 500

    @app.route('/api/crm/deals', methods=['GET'])
    @require_auth
    def list_crm_deals(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        page, limit, offset = crm_parse_page_args(default_limit=10, max_limit=100)
        try:
            panorama_ids = with_supabase_retry(
                lambda: crm_panorama_ids(require_supabase(), user_id, role),
                attempts=3,
            )
        except Exception as error:
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            return jsonify({'error': str(error)}), 500
        if not panorama_ids:
            empty_payload = crm_page_payload([], 0, page, limit)
            empty_payload['filter_options'] = {'clients': []}
            return jsonify(empty_payload)
        try:
            client_scope_ids = with_supabase_retry(
                lambda: crm_client_scope_ids(require_supabase(), user_id, role),
                attempts=3,
            )
        except Exception as error:
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            return jsonify({'error': str(error)}), 500
        if client_scope_ids is not None and not client_scope_ids:
            empty_payload = crm_page_payload([], 0, page, limit)
            empty_payload['filter_options'] = {'clients': []}
            return jsonify(empty_payload)
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
        except Exception as error:
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            return jsonify({'error': str(error)}), 500
        requested_client_id = (request.args.get('client_id') or '').strip() or None
        stage = str(request.args.get('stage') or '').strip().lower()
        project_name = str(request.args.get('project_name') or '').strip()
        contact_id = str(request.args.get('contact_id') or '').strip()
        search_query = str(request.args.get('q') or '').strip().lower()
        if requested_client_id and client_scope_ids is not None and requested_client_id not in client_scope_ids:
            return jsonify({'error': 'Forbidden for this client group'}), 403

        # Unfiltered by requested_client_id (unlike reference_interest_ids
        # below), so the client dropdown keeps every option the broker could
        # pick, not just the ones under whichever client is already selected.
        facet_reference_interest_ids = []
        if reference_scope_user_id:
            try:
                facet_reference_interest_ids, _facet_contact_ids = with_supabase_retry(
                    lambda: crm_reference_linked_ids(
                        require_supabase(),
                        reference_scope_user_id,
                        panorama_ids,
                        client_ids=client_scope_ids,
                    ),
                    attempts=3,
                )
            except Exception:
                facet_reference_interest_ids = []
        client_facet = _crm_deals_client_facet(
            sb,
            panorama_ids=panorama_ids,
            client_scope_ids=client_scope_ids,
            reference_scope_user_id=reference_scope_user_id,
            reference_interest_ids=facet_reference_interest_ids,
            crm_cache_get=crm_cache_get,
            crm_cache_set=crm_cache_set,
            crm_cache_version=crm_cache_version,
            user_id=user_id,
            role=role,
        )

        reference_interest_ids = []
        if reference_scope_user_id:
            if not requested_client_id:
                # Same query as the facet call above (no client filter to
                # narrow by) — reuse its result instead of re-querying.
                reference_interest_ids = facet_reference_interest_ids
            else:
                try:
                    reference_interest_ids, _reference_contact_ids = with_supabase_retry(
                        lambda: crm_reference_linked_ids(
                            require_supabase(),
                            reference_scope_user_id,
                            panorama_ids,
                            client_ids=client_scope_ids,
                            requested_client_id=requested_client_id,
                        ),
                        attempts=3,
                    )
                except Exception as error:
                    if is_transient_supabase_error(error):
                        return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
                    return jsonify({'error': str(error)}), 500
            if not reference_interest_ids:
                empty_payload = crm_page_payload([], 0, page, limit)
                empty_payload['filter_options'] = {'clients': client_facet}
                return jsonify(empty_payload)

        allowed_stages = ('new', 'contacted', 'site_visit', 'negotiation', 'won', 'lost')
        deal_sort_field, deal_sort_desc = crm_parse_sort_args(
            CRM_DEAL_SORT_FIELDS, default_field='updated_at', default_desc=True
        )
        cache_key = (
            'crm_deals',
            deal_sort_field,
            deal_sort_desc,
            crm_cache_version.get('v', 1),
            str(user_id),
            str(role or ''),
            tuple(panorama_ids),
            tuple(client_scope_ids) if isinstance(client_scope_ids, list) else '__ALL__',
            reference_scope_user_id or '',
            tuple(reference_interest_ids),
            requested_client_id or '',
            stage,
            project_name,
            contact_id,
            search_query,
            page,
            limit,
            offset,
        )
        cached = crm_cache_get(cache_key, ttl_seconds=3)
        if cached is not None:
            return jsonify(cached)

        try:
            def _fetch_deals_page():
                active_sb = require_supabase()
                query = (
                    active_sb.table('crm_deals')
                    .select(
                        'id, org_id, client_id, panorama_id, interest_id, contact_id, title, stage, is_active, '
                        'amount, currency, plots, project_name, notes, custom_fields, created_at, updated_at',
                        count='exact',
                    )
                    .in_('panorama_id', panorama_ids)
                )
                query = _apply_client_scope(
                    query,
                    requested_client_id=requested_client_id,
                    client_scope_ids=client_scope_ids,
                )
                if reference_scope_user_id:
                    query = query.in_('interest_id', reference_interest_ids)
                if stage in allowed_stages:
                    query = query.eq('stage', stage)
                if project_name:
                    query = query.eq('project_name', project_name)
                if contact_id:
                    query = query.eq('contact_id', contact_id)
                if search_query:
                    token = search_query.replace('%', '').replace('(', '').replace(')', '').replace(',', '')
                    if token:
                        query = query.or_(
                            f"title.ilike.%{token}%,project_name.ilike.%{token}%,amount.ilike.%{token}%"
                        )
                query = query.order(deal_sort_field, desc=deal_sort_desc)
                if deal_sort_field != 'updated_at':
                    query = query.order('updated_at', desc=True)
                return query.range(offset, offset + limit - 1).execute()

            response = with_supabase_retry(_fetch_deals_page, attempts=3)
            payload = crm_page_payload(
                response.data or [],
                int(getattr(response, 'count', None) or 0),
                page,
                limit,
            )
            payload['filter_options'] = {'clients': client_facet}
            crm_cache_set(cache_key, payload)
            return jsonify(payload)
        except Exception as error:
            message = str(error)
            if is_transient_supabase_error(error):
                return jsonify({'error': 'Temporary CRM connection issue. Please retry.'}), 503
            if 'crm_deals' in message and (
                'does not exist' in message.lower() or 'relation' in message.lower()
            ):
                return jsonify({
                    'error': 'crm_deals table not found. Run db/migration_crm_contacts_deals_quotes.sql in Supabase.'
                }), 503
            return jsonify({'error': message}), 500
