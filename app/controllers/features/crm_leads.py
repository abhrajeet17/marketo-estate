"""
CRM leads: the single interest/deal record.

Routes
  GET    /api/crm/me                          capabilities for the CRM shell
  POST   /api/public/buy-interests            public checkout form (no auth)
  POST   /api/crm/leads  (+ /api/buy-interests) manual interest from the CRM
  GET    /api/crm/leads/<id>
  PATCH  /api/crm/leads/<id>                  edit any field (deal fields need deal rights)
  POST   /api/crm/leads/<id>/plots            add / remove plots on an interest or deal
  POST   /api/crm/leads/<id>/reveal-contact   referring broker reveals the contact
  POST   /api/crm/leads/<id>/convert          interest -> deal (client admin / client user)
  POST   /api/crm/leads/<id>/move-stage       kanban drag
  DELETE /api/crm/leads/<id>

Listing lives in crm_records.py (one endpoint, filtered by record_status).
"""
from flask import jsonify, request

from app.core.auth import get_profile, require_auth
from app.core.database import get_supabase
from app.services import crm_lead_service as leads
from app.services.crm_lead_service import ValidationError
from app.services.panorama_service import get_panorama_by_id, get_panorama_with_access
from app.services.uam_reference_service import (
    CLIENT_MEMBER_ROLE_BROKER,
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    _is_broker_member_role,
    _normalize_client_member_role,
    _validate_project_reference_user,
    can_user_reveal_broker_referred_contact,
)


def _db_unavailable():
    return jsonify({'error': 'Database not configured'}), 503


def _schema_error(exc):
    """Friendly 503 when the unified table has not been created yet."""
    msg = str(exc or '')
    low = msg.lower()
    if 'crm_leads' in msg and ('does not exist' in low or 'relation' in low or 'schema cache' in low):
        return jsonify({'error': 'crm_leads table not found. Run db/migration_crm_unified_leads.sql in Supabase.'}), 503
    return None


def register_crm_lead_routes(
    app,
    *,
    crm_panorama_ids,
    crm_client_scope_ids,
    crm_interest_reference_scope_user_id,
    crm_pick_client_id_for_create,
    crm_cache_bump,
):
    # ------------------------------------------------------------------ scope
    def _resolve_scope(sb, user_id, role):
        panorama_ids = crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return None, (jsonify({'error': 'Forbidden'}), 403)
        client_scope_ids = crm_client_scope_ids(sb, user_id, role)
        if client_scope_ids is not None and not client_scope_ids:
            return None, (jsonify({'error': 'Forbidden'}), 403)
        reference_scope_user_id = crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        caps = leads.get_user_caps(sb, user_id, role)
        return {
            'panorama_ids': [int(p) for p in panorama_ids],
            'client_scope_ids': client_scope_ids,
            'reference_scope_user_id': reference_scope_user_id,
            'caps': caps,
        }, None

    def _shape(sb, row, scope, user_id, role):
        return leads.shape_lead_row(
            sb, row,
            user_id=user_id, role=role,
            reference_scope_user_id=scope.get('reference_scope_user_id'),
            caps=scope['caps'],
        )

    def _row_response(sb, row, scope, user_id, role, status_code=200, **extra):
        payload = {'success': True, 'lead': _shape(sb, row, scope, user_id, role)}
        payload.update(extra)
        return jsonify(payload), status_code

    def _apply_reference(sb, upd, raw_ref, *, panorama_id, client_id):
        """Validate a reference user for this project and stamp their role."""
        ref = str(raw_ref or '').strip()
        if not ref:
            upd['reference_user_id'] = None
            upd['reference_user_role'] = None
            return None
        reference_user_id, _catalog, reference_row = _validate_project_reference_user(
            sb, reference_user_id=ref, panorama_id=panorama_id, client_id=client_id,
        )
        if not reference_user_id:
            raise ValidationError('Selected reference is not available for this project', 'reference_user_id')
        upd['reference_user_id'] = reference_user_id
        role = _normalize_client_member_role((reference_row or {}).get('member_role')) or \
            leads.resolve_reference_user_role(sb, reference_user_id, client_id)
        upd['reference_user_role'] = role or None
        return reference_row

    def _is_client_admin_of(sb, uid, client_id):
        if not client_id:
            return False
        for m in leads.get_client_memberships(sb, uid):
            if str(m.get('client_id') or '') == str(client_id) and \
                    _normalize_client_member_role(m.get('member_role')) == CLIENT_MEMBER_ROLE_CLIENT_ADMIN:
                return True
        return False

    # --------------------------------------------------------------------- me
    @app.route('/api/crm/me', methods=['GET'])
    @require_auth
    def crm_me(user_id, role):
        sb = get_supabase()
        if not sb:
            return _db_unavailable()
        profile = get_profile(sb, user_id) or {}
        has_crm = False
        try:
            has_crm = len(crm_panorama_ids(sb, user_id, role)) > 0
        except Exception:
            has_crm = leads.is_platform_admin_role(role)
        is_broker = False
        is_client_admin = False
        is_client_user = False
        is_client_member = False
        client_group_id = ''
        client_group_name = ''
        client_group_names = []
        try:
            member_rows = sb.table('client_members').select('client_id, member_role').eq('user_id', user_id).execute()
            client_ids = []
            seen = set()
            for row in (member_rows.data or []):
                mr = _normalize_client_member_role(row.get('member_role', ''))
                if _is_broker_member_role(mr):
                    is_broker = True
                if mr == CLIENT_MEMBER_ROLE_CLIENT_ADMIN:
                    is_client_admin = True
                if mr == CLIENT_MEMBER_ROLE_CLIENT_USER:
                    is_client_user = True
                if mr in (CLIENT_MEMBER_ROLE_CLIENT_ADMIN, CLIENT_MEMBER_ROLE_CLIENT_USER, CLIENT_MEMBER_ROLE_BROKER):
                    cid = str(row.get('client_id') or '').strip()
                    if cid and cid not in seen:
                        seen.add(cid)
                        client_ids.append(cid)
            if client_ids:
                is_client_member = True
                clients_res = sb.table('clients').select('id, name').in_('id', client_ids).order('name').execute()
                for c in (clients_res.data or []):
                    name = str(c.get('name') or '').strip()
                    if name:
                        client_group_names.append(name)
                if clients_res.data:
                    first = clients_res.data[0] or {}
                    client_group_id = str(first.get('id') or '').strip()
                    client_group_name = str(first.get('name') or '').strip()
        except Exception:
            pass
        caps = leads.get_user_caps(sb, user_id, role)
        return jsonify({
            'user_id': user_id,
            'role': role,
            'org_id': profile.get('org_id'),
            'display_name': profile.get('display_name') or profile.get('email') or '',
            'has_crm_access': has_crm,
            'is_broker': is_broker or caps.get('is_broker', False),
            'is_client_admin': is_client_admin,
            'is_client_user': is_client_user,
            'can_manage_team': bool(is_client_admin and not is_broker),
            'is_client_member': is_client_member,
            'can_manage_deals': bool(caps.get('can_manage_deals')),
            'can_convert_leads': bool(caps.get('can_manage_deals')),
            'client_group_id': client_group_id,
            'client_group_name': client_group_name,
            'client_group_names': client_group_names,
        })

    # ------------------------------------------------------------- create (public)
    @app.route('/api/public/buy-interests', methods=['POST'])
    def public_create_buy_interest():
        sb = get_supabase()
        if not sb:
            return _db_unavailable()
        data = request.get_json(silent=True) or {}
        try:
            panorama_id = int(data.get('panorama_id'))
        except Exception:
            return jsonify({'error': 'panorama_id is required', 'field': 'panorama_id'}), 400
        panorama = get_panorama_by_id(sb, panorama_id)
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        try:
            fields = leads.parse_customer_fields(data, require_core=True)
            fields['customer_birthday'] = leads.birthday_value(data.get('customer_birthday') or data.get('birthday'))
            plot_ids = leads.coerce_plot_ids(data.get('items') or data.get('plots') or [])
            if not plot_ids:
                raise ValidationError('At least one plot is required', 'plots')
            snapshot = leads.build_plot_snapshot(sb, panorama, plot_ids)
            if not snapshot:
                raise ValidationError('No valid plots found', 'plots')
            requested_ref = str(data.get('reference_user_id') or '').strip()
            reference_user_id, reference_catalog, reference_row = _validate_project_reference_user(
                sb, reference_user_id=requested_ref, panorama_id=panorama_id,
            )
            if requested_ref and not reference_user_id:
                raise ValidationError('Selected reference is not available for this project', 'reference_user_id')
        except ValidationError as exc:
            return jsonify(exc.payload()), exc.status
        client_id = None
        if reference_row and (reference_row.get('client_ids') or []):
            client_id = str(reference_row['client_ids'][0])
        if not client_id:
            project_client_ids = list((reference_catalog or {}).get('client_ids') or [])
            if len(project_client_ids) == 1:
                client_id = str(project_client_ids[0])
        reference_role = (
            _normalize_client_member_role((reference_row or {}).get('member_role'))
            or (leads.resolve_reference_user_role(sb, reference_user_id, client_id) if reference_user_id else None)
        )
        if not reference_user_id:
            # No referring link: the interest belongs to the client team via its admin.
            reference_user_id, reference_role = leads.default_reference_for_client(sb, client_id)
        request_origin = str(data.get('origin') or '').strip().lower()
        lead_source = 'SalesTool' if request_origin == 'plot' else (fields.get('lead_source') or 'SalesTool')
        now = leads.now_iso()
        row = {
            'record_status': leads.STATUS_INTEREST,
            'org_id': panorama.get('org_id'),
            'panorama_id': panorama_id,
            'client_id': client_id,
            'submitted_by': None,
            'reference_user_id': reference_user_id,
            'reference_user_role': reference_role,
            'plots': snapshot,
            'notes': '',
            'custom_fields': leads.extract_custom_fields(data),
            'created_at': now,
            'updated_at': now,
        }
        for key, value in fields.items():
            row[key] = leads.text_or_null(key, value)
        row['lead_source'] = lead_source
        try:
            r = sb.table(leads.LEAD_TABLE).insert(row).execute()
            created = (r.data or [row])[0]
            crm_cache_bump()
            return jsonify({'success': True, 'buy_interest': created, 'lead': created}), 201
        except Exception as exc:
            schema = _schema_error(exc)
            if schema:
                return schema
            return jsonify({'error': str(exc)}), 500

    # --------------------------------------------------------- create (CRM user)
    @app.route('/api/crm/leads', methods=['POST'])
    @app.route('/api/buy-interests', methods=['POST'])
    @require_auth
    def create_crm_lead(user_id, role):
        sb = get_supabase()
        if not sb:
            return _db_unavailable()
        data = request.get_json(silent=True) or {}
        request_origin = str(data.get('origin') or '').strip().lower()
        try:
            panorama_id = int(data.get('panorama_id'))
        except Exception:
            panorama_id = None
        if not panorama_id and request_origin == 'manual_normal':
            # Normal (non-visual) projects have no panorama; anchor to the first CRM panorama.
            try:
                pano_ids = crm_panorama_ids(sb, user_id, role)
                if pano_ids:
                    panorama_id = int(pano_ids[0])
            except Exception:
                panorama_id = None
        if not panorama_id:
            return jsonify({'error': 'Project is required', 'field': 'panorama_id'}), 400
        panorama, _access = get_panorama_with_access(sb, panorama_id, user_id)
        if not panorama:
            allowed = set(int(p) for p in (crm_panorama_ids(sb, user_id, role) or []))
            panorama = get_panorama_by_id(sb, panorama_id) if panorama_id in allowed else None
        if not panorama:
            return jsonify({'error': 'Panorama not found'}), 404
        try:
            fields = leads.parse_customer_fields(data, require_core=True)
            fields['customer_birthday'] = leads.birthday_value(data.get('customer_birthday') or data.get('birthday'))
            plot_ids = leads.coerce_plot_ids(data.get('items') or data.get('plots') or [])
            normal_plot_ids = leads.coerce_plot_ids(data.get('normal_plot_ids') or [])
            snapshot = []
            if request_origin == 'manual_normal':
                snapshot = leads.build_normal_plot_snapshot(sb, user_id, normal_plot_ids or plot_ids)
            else:
                if not plot_ids:
                    raise ValidationError('Select at least one plot', 'plots')
                snapshot = leads.build_plot_snapshot(sb, panorama, plot_ids)
            if not snapshot:
                raise ValidationError('No valid plots found', 'plots')
            client_id, client_err = crm_pick_client_id_for_create(
                sb, user_id, role, requested_client_id=data.get('client_id'), panorama_id=panorama_id,
            )
            if client_err:
                return client_err
            reference_scope_user_id = crm_interest_reference_scope_user_id(
                sb, user_id, role, client_ids=[client_id] if client_id else None,
            )
            # The reference is not user-selectable: a broker's own interests reference
            # the broker; everything the client team brings in references the client admin.
            upd_ref = {}
            if reference_scope_user_id:
                _apply_reference(sb, upd_ref, reference_scope_user_id, panorama_id=panorama_id, client_id=client_id)
                upd_ref['reference_user_role'] = CLIENT_MEMBER_ROLE_BROKER
            else:
                if _is_client_admin_of(sb, user_id, client_id):
                    upd_ref = {'reference_user_id': str(user_id), 'reference_user_role': CLIENT_MEMBER_ROLE_CLIENT_ADMIN}
                else:
                    admin_uid, admin_role = leads.default_reference_for_client(sb, client_id)
                    upd_ref = {'reference_user_id': admin_uid, 'reference_user_role': admin_role}
        except ValidationError as exc:
            return jsonify(exc.payload()), exc.status
        lead_source = 'SalesTool' if request_origin == 'plot' else (fields.get('lead_source') or 'SalesTool')
        now = leads.now_iso()
        row = {
            'record_status': leads.STATUS_INTEREST,
            'org_id': panorama.get('org_id'),
            'panorama_id': panorama_id,
            'client_id': client_id,
            'submitted_by': user_id,
            'reference_user_id': upd_ref.get('reference_user_id'),
            'reference_user_role': upd_ref.get('reference_user_role'),
            'plots': snapshot,
            'custom_fields': leads.extract_custom_fields(data),
            'created_at': now,
            'updated_at': now,
        }
        for key, value in fields.items():
            row[key] = leads.text_or_null(key, value)
        row['lead_source'] = lead_source
        row['notes'] = row.get('notes') or ''
        try:
            r = sb.table(leads.LEAD_TABLE).insert(row).execute()
            created = (r.data or [row])[0]
        except Exception as exc:
            schema = _schema_error(exc)
            if schema:
                return schema
            return jsonify({'error': str(exc)}), 500
        crm_cache_bump()
        scope, err = _resolve_scope(sb, user_id, role)
        if err or not scope:
            return jsonify({'success': True, 'lead': created, 'buy_interest': created}), 201
        return _row_response(sb, created, scope, user_id, role, 201, buy_interest=created)

    # ------------------------------------------------------------------- read
    @app.route('/api/crm/leads/<lead_id>', methods=['GET'])
    @require_auth
    def get_crm_lead(user_id, role, lead_id):
        sb = get_supabase()
        if not sb:
            return _db_unavailable()
        scope, err = _resolve_scope(sb, user_id, role)
        if err:
            return err
        row = leads.get_lead_for_user(sb, lead_id, scope)
        if not row:
            return jsonify({'error': 'Not found or access denied'}), 404
        return _row_response(sb, row, scope, user_id, role)

    # ------------------------------------------------------------------- edit
    @app.route('/api/crm/leads/<lead_id>', methods=['PATCH', 'PUT'])
    @require_auth
    def update_crm_lead(user_id, role, lead_id):
        sb = get_supabase()
        if not sb:
            return _db_unavailable()
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or not data:
            return jsonify({'error': 'Body required'}), 400
        scope, err = _resolve_scope(sb, user_id, role)
        if err:
            return err
        row = leads.get_lead_for_user(sb, lead_id, scope)
        if not row:
            return jsonify({'error': 'Not found or access denied'}), 404
        caps = scope['caps']
        is_deal = str(row.get('record_status') or '') == leads.STATUS_DEAL
        if is_deal and not caps.get('can_manage_deals'):
            return jsonify({'error': 'Only client admins and client users can edit deals'}), 403
        current = _shape(sb, row, scope, user_id, role)
        touches_contact = any(key in data for key in leads.CONTACT_FIELDS) or any(
            alias in data for alias in ('email', 'phone', 'address', 'street', 'city', 'state', 'country', 'zip_code', 'birthday')
        )
        if current.get('contact_hidden') and touches_contact:
            return jsonify({'error': 'Contact details are hidden until the referring broker reveals them'}), 403

        upd = {}
        try:
            fields = leads.parse_customer_fields(data, require_core=False)
            for key, value in fields.items():
                if key in leads.CORE_REQUIRED_FIELDS and not value:
                    raise ValidationError(f"{leads.FIELD_LABELS[key]} is required", key)
                upd[key] = leads.text_or_null(key, value)
            if 'customer_birthday' in data or 'birthday' in data:
                upd['customer_birthday'] = leads.birthday_value(
                    data.get('customer_birthday') if 'customer_birthday' in data else data.get('birthday')
                )
            if is_deal:
                for key in leads.DEAL_ONLY_FIELDS:
                    if key in data:
                        value = leads.clean_text(data.get(key), key)
                        if key == 'deal_title' and not value:
                            raise ValidationError('Deal name is required', 'deal_title')
                        if key == 'deal_currency':
                            value = leads.normalize_currency(value)
                        upd[key] = value
                if 'deal_stage' in data:
                    stage = leads.normalize_deal_stage(data.get('deal_stage'))
                    if not stage:
                        raise ValidationError('Invalid deal stage', 'deal_stage')
                    upd['deal_stage'] = stage
                    upd['deal_is_active'] = leads.deal_is_active_for_stage(stage)
            # The reference is fixed at creation time and is not editable.
            if 'assigned_to' in data:
                raw_at = str(data.get('assigned_to') or '').strip()
                upd['assigned_to'] = raw_at or None
                upd['assigned_at'] = leads.now_iso() if raw_at else None
            if 'plots' in data:
                plots = leads.clean_plot_list(data.get('plots'))
                if not plots:
                    raise ValidationError('A record must keep at least one plot', 'plots')
                upd['plots'] = plots
        except ValidationError as exc:
            return jsonify(exc.payload()), exc.status

        # Recompose the single-line address when only parts were edited.
        if any(k in upd for k in leads.ADDRESS_PART_FIELDS) and 'customer_address' not in upd:
            merged = dict(row)
            merged.update(upd)
            upd['customer_address'] = leads.compose_address([merged.get(k) for k in leads.ADDRESS_PART_FIELDS]) or None

        custom = leads.extract_custom_fields(data)
        if custom:
            existing_custom = row.get('custom_fields') if isinstance(row.get('custom_fields'), dict) else {}
            merged_custom = dict(existing_custom)
            merged_custom.update(custom)
            upd['custom_fields'] = merged_custom

        if not upd:
            return jsonify({'error': 'Nothing to update'}), 400
        upd['updated_at'] = leads.now_iso()
        try:
            rows = leads.scoped_update(sb, lead_id, upd, scope)
        except Exception as exc:
            schema = _schema_error(exc)
            if schema:
                return schema
            return jsonify({'error': str(exc)}), 500
        if not rows:
            return jsonify({'error': 'Not found or access denied'}), 404
        crm_cache_bump()
        return _row_response(sb, rows[0], scope, user_id, role)

    # ------------------------------------------------------------------ plots
    @app.route('/api/crm/leads/<lead_id>/plots', methods=['POST'])
    @require_auth
    def update_crm_lead_plots(user_id, role, lead_id):
        sb = get_supabase()
        if not sb:
            return _db_unavailable()
        data = request.get_json(silent=True) or {}
        scope, err = _resolve_scope(sb, user_id, role)
        if err:
            return err
        row = leads.get_lead_for_user(sb, lead_id, scope)
        if not row:
            return jsonify({'error': 'Not found or access denied'}), 404
        is_deal = str(row.get('record_status') or '') == leads.STATUS_DEAL
        if is_deal and not scope['caps'].get('can_manage_deals'):
            return jsonify({'error': 'Only client admins and client users can edit deals'}), 403
        add_ids = leads.coerce_plot_ids(data.get('add_plot_ids') or [])
        normal_ids = leads.coerce_plot_ids(data.get('normal_plot_ids') or [])
        remove_keys = data.get('remove_plot_keys') or data.get('remove_plot_ids') or []
        if not isinstance(remove_keys, list):
            remove_keys = []
        if not add_ids and not normal_ids and not remove_keys:
            return jsonify({'error': 'Nothing to change', 'field': 'plots'}), 400
        additions = []
        if add_ids:
            panorama = get_panorama_by_id(sb, int(row.get('panorama_id')))
            additions.extend(leads.build_plot_snapshot(sb, panorama, add_ids))
            if not additions:
                return jsonify({'error': 'Selected plots are not part of this project', 'field': 'plots'}), 400
        if normal_ids:
            owner = row.get('submitted_by') or user_id
            normal_snapshot = leads.build_normal_plot_snapshot(sb, owner, normal_ids)
            if not normal_snapshot and str(owner) != str(user_id):
                normal_snapshot = leads.build_normal_plot_snapshot(sb, user_id, normal_ids)
            additions.extend(normal_snapshot)
        current_plots = row.get('plots') if isinstance(row.get('plots'), list) else []
        plots = leads.remove_plots(current_plots, remove_keys)
        plots = leads.merge_plots(plots, additions)
        if not plots:
            return jsonify({'error': 'A record must keep at least one plot', 'field': 'plots'}), 400
        upd = {'plots': plots, 'updated_at': leads.now_iso()}
        rows = leads.scoped_update(sb, lead_id, upd, scope)
        if not rows:
            return jsonify({'error': 'Not found or access denied'}), 404
        crm_cache_bump()
        return _row_response(sb, rows[0], scope, user_id, role, added=len(additions))

    # ----------------------------------------------------------------- reveal
    @app.route('/api/crm/leads/<lead_id>/reveal-contact', methods=['POST'])
    @app.route('/api/buy-interests/<lead_id>/reveal-contact', methods=['POST'])
    @require_auth
    def reveal_crm_lead_contact(user_id, role, lead_id):
        sb = get_supabase()
        if not sb:
            return _db_unavailable()
        scope, err = _resolve_scope(sb, user_id, role)
        if err:
            return err
        row = leads.get_lead_for_user(sb, lead_id, scope)
        if not row:
            return jsonify({'error': 'Not found or access denied'}), 404
        if not can_user_reveal_broker_referred_contact(user_id, row):
            if not leads.contact_requires_reveal(row) and not str(row.get('contact_revealed_at') or '').strip():
                return jsonify({'error': 'Only broker-referred contacts need to be revealed'}), 403
            if str(row.get('contact_revealed_at') or '').strip():
                return jsonify({'error': 'Contact is already revealed'}), 409
            return jsonify({'error': 'Only the referring broker can reveal this contact'}), 403
        now = leads.now_iso()
        rows = leads.scoped_update(sb, lead_id, {'contact_revealed_at': now, 'updated_at': now}, scope)
        if not rows:
            return jsonify({'error': 'Not found or access denied'}), 404
        crm_cache_bump()
        return _row_response(sb, rows[0], scope, user_id, role, contact_revealed_at=now)

    # ---------------------------------------------------------------- convert
    @app.route('/api/crm/leads/<lead_id>/convert', methods=['POST'])
    @require_auth
    def convert_crm_lead(user_id, role, lead_id):
        sb = get_supabase()
        if not sb:
            return _db_unavailable()
        data = request.get_json(silent=True) or {}
        scope, err = _resolve_scope(sb, user_id, role)
        if err:
            return err
        row = leads.get_lead_for_user(sb, lead_id, scope)
        if not row:
            return jsonify({'error': 'Not found or access denied'}), 404
        reason = leads.convert_block_reason(row, user_id, scope['caps'])
        if reason:
            code = 409 if str(row.get('record_status') or '') == leads.STATUS_DEAL else 403
            return jsonify({'error': reason}), code
        pinfo = leads.panorama_info_map(sb, [row.get('panorama_id')]).get(int(row.get('panorama_id'))) or {}
        try:
            # A blank name sent by the form is an error; only an absent field defaults.
            if 'deal_title' in data or 'title' in data:
                deal_title = leads.clean_text(data.get('deal_title') if 'deal_title' in data else data.get('title'), 'deal_title')
            else:
                deal_title = leads.clean_text(row.get('customer_name') or 'Deal', 'deal_title')
            if not deal_title:
                raise ValidationError('Deal name is required', 'deal_title')
            stage = leads.normalize_deal_stage(data.get('deal_stage') or data.get('stage') or 'new')
            if not stage:
                raise ValidationError('Invalid deal stage', 'deal_stage')
            amount = leads.clean_text(data.get('deal_amount') if 'deal_amount' in data else data.get('amount'), 'deal_amount')
            currency = leads.normalize_currency(data.get('deal_currency') or data.get('currency') or 'INR')
            project_name = leads.clean_text(
                data.get('deal_project_name') or data.get('project_name') or pinfo.get('workspace_name') or pinfo.get('name') or '',
                'deal_project_name',
            )
            deal_notes = leads.clean_text(data.get('notes'), 'notes') if 'notes' in data else ''
        except ValidationError as exc:
            return jsonify(exc.payload()), exc.status
        current_plots = row.get('plots') if isinstance(row.get('plots'), list) else []
        plots = current_plots
        selection = data.get('plots')
        if isinstance(selection, list) and selection:
            wanted = set()
            for p in selection:
                if isinstance(p, dict):
                    wanted.add(leads.plot_identity(p))
                elif p is not None and str(p).strip():
                    wanted.add('id:' + str(p).strip())
            picked = [p for p in current_plots if leads.plot_identity(p) in wanted]
            if picked:
                plots = picked
        if not plots:
            return jsonify({'error': 'Select at least one plot for the deal', 'field': 'plots'}), 400
        if not amount:
            amount = leads.deal_amount_from_plots(plots)
        notes = str(row.get('notes') or '').strip()
        if deal_notes and deal_notes not in notes:
            notes = (notes + '\n\n' + deal_notes).strip() if notes else deal_notes
        now = leads.now_iso()
        upd = {
            'record_status': leads.STATUS_DEAL,
            'deal_title': deal_title,
            'deal_stage': stage,
            'deal_is_active': leads.deal_is_active_for_stage(stage),
            'deal_amount': amount,
            'deal_currency': currency,
            'deal_project_name': project_name,
            'plots': plots,
            'notes': notes,
            'converted_at': now,
            'converted_by': user_id,
            'updated_at': now,
        }
        custom = leads.extract_custom_fields(
            data,
            known_keys={'deal_title', 'title', 'deal_stage', 'stage', 'deal_amount', 'amount', 'deal_currency',
                        'currency', 'deal_project_name', 'project_name', 'notes', 'plots'},
        )
        if custom:
            existing_custom = row.get('custom_fields') if isinstance(row.get('custom_fields'), dict) else {}
            merged = dict(existing_custom)
            merged.update(custom)
            upd['custom_fields'] = merged
        # Guard against a concurrent conversion: only flip rows that are still interests.
        try:
            query = sb.table(leads.LEAD_TABLE).update(upd).eq('id', str(lead_id)).eq('record_status', leads.STATUS_INTEREST)
            query = leads.apply_record_scope(query, scope)
            rows = query.execute().data or []
        except Exception as exc:
            schema = _schema_error(exc)
            if schema:
                return schema
            return jsonify({'error': str(exc)}), 500
        if not rows:
            return jsonify({'error': 'This interest was already converted'}), 409
        crm_cache_bump()
        return _row_response(sb, rows[0], scope, user_id, role, 201, deal=rows[0])

    # ------------------------------------------------------------- move stage
    @app.route('/api/crm/leads/<lead_id>/move-stage', methods=['POST'])
    @require_auth
    def move_crm_lead_stage(user_id, role, lead_id):
        sb = get_supabase()
        if not sb:
            return _db_unavailable()
        data = request.get_json(silent=True) or {}
        stage = leads.normalize_deal_stage(data.get('deal_stage') or data.get('stage'))
        if not stage:
            return jsonify({'error': 'Invalid deal stage', 'field': 'deal_stage'}), 400
        scope, err = _resolve_scope(sb, user_id, role)
        if err:
            return err
        if not scope['caps'].get('can_manage_deals'):
            return jsonify({'error': 'Only client admins and client users can move deals'}), 403
        row = leads.get_lead_for_user(sb, lead_id, scope)
        if not row:
            return jsonify({'error': 'Not found or access denied'}), 404
        if str(row.get('record_status') or '') != leads.STATUS_DEAL:
            return jsonify({'error': 'Only deals have stages'}), 409
        upd = {
            'deal_stage': stage,
            'deal_is_active': leads.deal_is_active_for_stage(stage),
            'updated_at': leads.now_iso(),
        }
        rows = leads.scoped_update(sb, lead_id, upd, scope)
        if not rows:
            return jsonify({'error': 'Not found or access denied'}), 404
        crm_cache_bump()
        return _row_response(sb, rows[0], scope, user_id, role)

    # ----------------------------------------------------------------- delete
    @app.route('/api/crm/leads/<lead_id>', methods=['DELETE'])
    @app.route('/api/buy-interests/<lead_id>', methods=['DELETE'])
    @require_auth
    def delete_crm_lead(user_id, role, lead_id):
        sb = get_supabase()
        if not sb:
            return _db_unavailable()
        scope, err = _resolve_scope(sb, user_id, role)
        if err:
            return err
        row = leads.get_lead_for_user(sb, lead_id, scope)
        if not row:
            return jsonify({'error': 'Not found or access denied'}), 404
        is_deal = str(row.get('record_status') or '') == leads.STATUS_DEAL
        if is_deal and not scope['caps'].get('can_manage_deals'):
            return jsonify({'error': 'Only client admins and client users can delete deals'}), 403
        try:
            leads.scoped_delete(sb, lead_id, scope)
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500
        crm_cache_bump()
        return jsonify({'success': True, 'id': str(lead_id), 'record_status': row.get('record_status')})
