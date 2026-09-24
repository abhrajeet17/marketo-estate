"""
CRM dashboard statistics for the customer dashboard charts.

  GET /api/crm/dashboard-stats?days=7|14|30|90

Response:
  {
    deals_by_stage:    [{key, label, count}]            every stage, all deals in scope
    interests_per_day: [{date: "YYYY-MM-DD", count}]    every day in the window (UTC), zeros included
    totals:            {interests, deals, won, open}
    window:            {days, from, to}
  }

Scope is resolved exactly like the CRM record listing so the dashboard only
counts records the caller could see in the CRM.
"""
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from app.core.auth import require_auth
from app.core.database import (
    get_supabase,
    is_transient_supabase_error,
    require_supabase,
    with_supabase_retry,
)
from app.services import crm_lead_service as leads

STATS_COLUMNS = 'record_status, deal_stage, created_at'
STATS_CHUNK_SIZE = 1000
STATS_ROW_CAP = 20000
STATS_CACHE_TTL_SECONDS = 15
ALLOWED_WINDOW_DAYS = (7, 14, 30, 90)
DEFAULT_WINDOW_DAYS = 14

_TRANSIENT_MESSAGE = 'Temporary CRM connection issue. Please retry.'
_MISSING_TABLE_MESSAGE = 'crm_leads table not found. Run db/migration_crm_unified_leads.sql in Supabase.'


def _parse_window_days(raw):
    try:
        days = int(str(raw or '').strip())
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DAYS
    return days if days in ALLOWED_WINDOW_DAYS else DEFAULT_WINDOW_DAYS


def _window_dates(days, today=None):
    """List of UTC dates (oldest first) covering the last `days` days including today."""
    end = today or datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)
    return [start + timedelta(days=offset) for offset in range(days)]


def _created_date_utc(value):
    """UTC calendar date of a timestamptz value from Supabase, or None."""
    text = str(value or '').strip()
    if not text:
        return None
    iso = text[:-1] + '+00:00' if text.endswith('Z') or text.endswith('z') else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        try:
            return datetime.strptime(text[:10], '%Y-%m-%d').date()
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date()


def _is_missing_table_error(error):
    message = str(error or '')
    low = message.lower()
    return 'crm_leads' in message and ('does not exist' in low or 'relation' in low or 'schema cache' in low)


def _error_response(error):
    if is_transient_supabase_error(error):
        return jsonify({'error': _TRANSIENT_MESSAGE}), 503
    if _is_missing_table_error(error):
        return jsonify({'error': _MISSING_TABLE_MESSAGE}), 503
    return jsonify({'error': str(error)}), 500


def build_dashboard_stats(rows, days, today=None):
    """Aggregate raw crm_leads rows (record_status, deal_stage, created_at) into the payload."""
    window = _window_dates(days, today)
    per_day = {day.isoformat(): 0 for day in window}
    stage_counts = {stage: 0 for stage in leads.DEAL_STAGES}
    interests = 0
    deals = 0
    for row in rows or []:
        status = str(row.get('record_status') or '')
        if status == leads.STATUS_DEAL:
            deals += 1
            stage = leads.normalize_deal_stage(row.get('deal_stage')) or 'new'
            if stage not in stage_counts:
                stage = 'new'
            stage_counts[stage] += 1
        elif status == leads.STATUS_INTEREST:
            interests += 1
            created = _created_date_utc(row.get('created_at'))
            if created is not None:
                key = created.isoformat()
                if key in per_day:
                    per_day[key] += 1
    won = stage_counts.get('won', 0)
    closed = won + stage_counts.get('lost', 0)
    return {
        'deals_by_stage': [
            {'key': stage, 'label': leads.DEAL_STAGE_LABELS.get(stage, stage), 'count': int(stage_counts[stage])}
            for stage in leads.DEAL_STAGES
        ],
        'interests_per_day': [{'date': day.isoformat(), 'count': int(per_day[day.isoformat()])} for day in window],
        'totals': {
            'interests': int(interests),
            'deals': int(deals),
            'won': int(won),
            'open': int(max(deals - closed, 0)),
        },
        'window': {'days': int(days), 'from': window[0].isoformat(), 'to': window[-1].isoformat()},
    }


def _fetch_scoped_rows(scope):
    """Page through crm_leads in scope, selecting only the three columns the stats need."""
    active_sb = require_supabase()
    rows = []
    offset = 0
    while offset < STATS_ROW_CAP:
        upper = min(offset + STATS_CHUNK_SIZE, STATS_ROW_CAP) - 1
        query = active_sb.table(leads.LEAD_TABLE).select(STATS_COLUMNS)
        query = leads.apply_record_scope(query, scope)
        chunk = query.order('created_at', desc=True).range(offset, upper).execute().data or []
        rows.extend(chunk)
        if len(chunk) < (upper - offset + 1):
            break
        offset = upper + 1
    return rows


def register_crm_dashboard_routes(
    app,
    *,
    crm_panorama_ids,
    crm_client_scope_ids,
    crm_interest_reference_scope_user_id,
    crm_cache_get,
    crm_cache_set,
    crm_cache_version,
):
    @app.route('/api/crm/dashboard-stats', methods=['GET'])
    @require_auth
    def crm_dashboard_stats(user_id, role):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        days = _parse_window_days(request.args.get('days'))
        empty = build_dashboard_stats([], days)

        try:
            panorama_ids = with_supabase_retry(lambda: crm_panorama_ids(require_supabase(), user_id, role), attempts=3)
        except Exception as error:
            return _error_response(error)
        if not panorama_ids:
            return jsonify(empty)
        try:
            client_scope_ids = with_supabase_retry(lambda: crm_client_scope_ids(require_supabase(), user_id, role), attempts=3)
        except Exception as error:
            return _error_response(error)
        if client_scope_ids is not None and not client_scope_ids:
            return jsonify(empty)
        try:
            reference_scope_user_id = with_supabase_retry(
                lambda: crm_interest_reference_scope_user_id(require_supabase(), user_id, role, client_scope_ids),
                attempts=3,
            )
        except Exception as error:
            return _error_response(error)
        caps = leads.get_user_caps(sb, user_id, role)
        scope = {
            'panorama_ids': [int(p) for p in panorama_ids],
            'client_scope_ids': client_scope_ids,
            'reference_scope_user_id': reference_scope_user_id,
            'caps': caps,
        }

        cache_key = (
            'crm_dashboard_stats',
            crm_cache_version.get('v', 1),
            str(user_id),
            str(role or ''),
            tuple(scope['panorama_ids']),
            tuple(client_scope_ids) if isinstance(client_scope_ids, list) else '__ALL__',
            reference_scope_user_id or '',
            days,
        )
        cached = crm_cache_get(cache_key, ttl_seconds=STATS_CACHE_TTL_SECONDS)
        if cached is not None:
            return jsonify(cached)

        try:
            rows = with_supabase_retry(lambda: _fetch_scoped_rows(scope), attempts=3)
        except Exception as error:
            return _error_response(error)
        payload = build_dashboard_stats(rows, days)
        crm_cache_set(cache_key, payload)
        return jsonify(payload)
