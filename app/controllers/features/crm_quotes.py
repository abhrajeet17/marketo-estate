"""
Deal quotations. A "deal" is a crm_leads row with record_status = 'deal';
the lead row is also the contact.

  POST /api/crm/deals/<deal_id>/quotation/preview
  POST /api/crm/deals/<deal_id>/quotation/share
  GET  /api/crm/deals/<deal_id>/quotations
  PATCH /api/crm/deals/<deal_id>/quotations/<quote_id>
  GET  /api/crm/deals/<deal_id>/quotation/<quote_id>?token=   (public, tokenised)
"""
import json
import secrets
from datetime import datetime
from html import escape

from flask import Response, jsonify, request

from app import config as app_config
from app.core.auth import require_auth
from app.core.database import get_supabase
from app.services import crm_lead_service as leads
from app.services.email_service import send_email as send_smtp_email
from app.services.uam_reference_service import viewer_should_mask_broker_referred_contact

QUOTE_STATUSES = ('draft', 'sent', 'accepted', 'rejected', 'superseded')


def _merge_quote_template_inputs(template_payload, request_inputs):
    tp = leads.safe_json(template_payload, {})
    rq = leads.safe_json(request_inputs, {})
    if isinstance(tp, dict) and isinstance(rq, dict):
        merged = dict(tp)
        merged.update(rq)
        return merged
    if isinstance(rq, dict):
        return rq
    return tp if isinstance(tp, dict) else {}


def _quote_deal_payload(row):
    return {
        'id': str(row.get('id')),
        'org_id': row.get('org_id'),
        'client_id': row.get('client_id'),
        'panorama_id': row.get('panorama_id'),
        'contact_id': str(row.get('id')),
        'title': row.get('deal_title') or row.get('customer_name') or '',
        'stage': row.get('deal_stage') or 'new',
        'amount': row.get('deal_amount') or '',
        'currency': row.get('deal_currency') or 'INR',
        'plots': row.get('plots') if isinstance(row.get('plots'), list) else [],
        'project_name': row.get('deal_project_name') or '',
    }


def _quote_contact_payload(row):
    return {
        'id': str(row.get('id')),
        'full_name': row.get('customer_name') or '',
        'email': row.get('customer_email') or '',
        'phone': row.get('customer_phone') or '',
        'address': row.get('customer_address') or '',
        'birthday': str(row.get('customer_birthday') or '')[:10],
    }


def register_crm_quote_routes(
    app,
    *,
    crm_panorama_ids,
    crm_client_scope_ids,
    crm_interest_reference_scope_user_id,
    crm_cache_bump,
):
    def _resolve_scope(sb, user_id, role):
        panorama_ids = crm_panorama_ids(sb, user_id, role)
        if not panorama_ids:
            return None, (jsonify({'error': 'Forbidden'}), 403)
        client_scope_ids = crm_client_scope_ids(sb, user_id, role)
        if client_scope_ids is not None and not client_scope_ids:
            return None, (jsonify({'error': 'Forbidden'}), 403)
        reference_scope_user_id = crm_interest_reference_scope_user_id(sb, user_id, role, client_scope_ids)
        return {
            'panorama_ids': [int(p) for p in panorama_ids],
            'client_scope_ids': client_scope_ids,
            'reference_scope_user_id': reference_scope_user_id,
            'caps': leads.get_user_caps(sb, user_id, role),
        }, None

    def _get_deal(sb, deal_id, scope):
        row = leads.get_lead_for_user(sb, deal_id, scope)
        if not row or str(row.get('record_status') or '') != leads.STATUS_DEAL:
            return None
        return row

    def _deny_hidden_contact(sb, user_id, role, scope, row):
        """A quote snapshots the raw contact; viewers the broker has not revealed
        the contact to must not mint one."""
        if (
            leads.contact_requires_reveal(row)
            and str(row.get('reference_user_id') or '') != str(user_id)
            and viewer_should_mask_broker_referred_contact(sb, user_id, role, scope.get('reference_scope_user_id'))
        ):
            return jsonify({'error': 'Contact details are hidden until the referring broker reveals them'}), 403
        return None

    @app.route('/api/crm/deals/<deal_id>/quotation/preview', methods=['POST'])
    @require_auth
    def preview_deal_quote(user_id, role, deal_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        scope, err = _resolve_scope(sb, user_id, role)
        if err:
            return err
        deal = _get_deal(sb, deal_id, scope)
        if not deal:
            return jsonify({'error': 'Deal not found'}), 404
        deny = _deny_hidden_contact(sb, user_id, role, scope, deal)
        if deny:
            return deny
        payload = request.get_json(silent=True) or {}
        template_id = str(payload.get('template_id') or '').strip() or None
        inputs_raw = {k: v for k, v in payload.items() if k != 'template_id'}
        tpl_payload = {}
        resolved_template_id = None
        if template_id:
            tr = (
                sb.table('crm_quote_templates')
                .select('id, org_id, panorama_id, template_payload')
                .eq('id', template_id)
                .limit(1)
                .execute()
            )
            if not tr.data:
                return jsonify({'error': 'Template not found'}), 404
            tpl = tr.data[0]
            d_org = deal.get('org_id')
            t_org = tpl.get('org_id')
            if d_org and t_org and str(d_org) != str(t_org):
                return jsonify({'error': 'Template does not belong to this deal organization'}), 400
            t_pano = tpl.get('panorama_id')
            if t_pano is not None and int(deal.get('panorama_id') or 0) != int(t_pano):
                return jsonify({'error': 'Template is not valid for this panorama'}), 400
            tpl_payload = tpl.get('template_payload') or {}
            resolved_template_id = str(tpl.get('id'))
        quote_payload = {
            'deal': _quote_deal_payload(deal),
            'contact': _quote_contact_payload(deal),
            'inputs': _merge_quote_template_inputs(tpl_payload, inputs_raw),
            'generated_at': datetime.utcnow().isoformat(),
        }
        token = secrets.token_urlsafe(24)
        now = datetime.utcnow().isoformat()
        row = {
            'deal_id': str(deal_id),
            'contact_id': str(deal_id),
            'template_id': resolved_template_id,
            'quote_payload': quote_payload,
            'share_token': token,
            'sent_to_email': '',
            'sent_to_phone': '',
            'shared_via': '',
            'sent_at': None,
            'status': 'draft',
            'created_by': user_id,
            'created_at': now,
            'updated_at': now,
        }
        try:
            r = sb.table('crm_deal_quotes').insert(row).execute()
        except Exception as exc:
            msg = str(exc)
            if 'crm_deal_quotes' in msg and ('foreign key' in msg.lower() or 'violates' in msg.lower()):
                return jsonify({'error': 'Quotes are not linked to the unified CRM table yet. Run db/migration_crm_unified_leads.sql.'}), 503
            return jsonify({'error': msg}), 500
        quote = (r.data or [row])[0]
        share_url = f"{request.url_root.rstrip('/')}/api/crm/deals/{deal_id}/quotation/{quote.get('id')}?token={token}"
        crm_cache_bump()
        return jsonify({'success': True, 'quote': quote, 'share_url': share_url})

    @app.route('/api/crm/deals/<deal_id>/quotation/share', methods=['POST'])
    @require_auth
    def share_deal_quote(user_id, role, deal_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        scope, err = _resolve_scope(sb, user_id, role)
        if err:
            return err
        deal = _get_deal(sb, deal_id, scope)
        if not deal:
            return jsonify({'error': 'Deal not found or access denied'}), 404
        deny = _deny_hidden_contact(sb, user_id, role, scope, deal)
        if deny:
            return deny
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
        to_email = str(data.get('email') or '').strip()[:254]
        to_phone = str(data.get('phone') or '').strip()[:32]
        if to_email and ('@' not in to_email or ' ' in to_email):
            return jsonify({'error': 'Invalid recipient email'}), 400
        if not to_email:
            to_email = str(deal.get('customer_email') or '').strip()
            to_phone = to_phone or str(deal.get('customer_phone') or '').strip()
        if not to_email:
            return jsonify({'error': 'No recipient email found'}), 400
        share_url = f"{request.url_root.rstrip('/')}/api/crm/deals/{deal_id}/quotation/{quote_id}?token={quote.get('share_token')}"
        subject = f"Quotation for {deal.get('deal_title') or deal.get('customer_name') or 'your deal'}"
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

    @app.route('/api/crm/deals/<deal_id>/quotations', methods=['GET'])
    @require_auth
    def list_deal_quotations(user_id, role, deal_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        scope, err = _resolve_scope(sb, user_id, role)
        if err:
            return err
        deal = _get_deal(sb, deal_id, scope)
        if not deal:
            return jsonify({'error': 'Deal not found'}), 404
        try:
            qr = (
                sb.table('crm_deal_quotes')
                .select('id, deal_id, contact_id, template_id, status, shared_via, sent_to_email, sent_at, created_at, updated_at')
                .eq('deal_id', str(deal_id))
                .order('created_at', desc=True)
                .limit(200)
                .execute()
            )
            rows = qr.data or []
            for row in rows:
                for k in ('created_at', 'updated_at', 'sent_at'):
                    if row.get(k):
                        row[k] = str(row[k])
                if row.get('template_id'):
                    row['template_id'] = str(row['template_id'])
            return jsonify(rows)
        except Exception as e:
            msg = str(e)
            if 'status' in msg or 'template_id' in msg:
                return jsonify({'error': 'Run db migration migration_crm_lead_assign_quote_templates.sql for quotation columns.'}), 503
            return jsonify({'error': msg}), 500

    @app.route('/api/crm/deals/<deal_id>/quotations/<quote_id>', methods=['PATCH'])
    @require_auth
    def patch_deal_quotation(user_id, role, deal_id, quote_id):
        sb = get_supabase()
        if not sb:
            return jsonify({'error': 'Database not configured'}), 503
        scope, err = _resolve_scope(sb, user_id, role)
        if err:
            return err
        deal = _get_deal(sb, deal_id, scope)
        if not deal:
            return jsonify({'error': 'Deal not found'}), 404
        qr = (
            sb.table('crm_deal_quotes')
            .select('id, quote_payload, status')
            .eq('id', str(quote_id))
            .eq('deal_id', str(deal_id))
            .limit(1)
            .execute()
        )
        if not qr.data:
            return jsonify({'error': 'Quote not found'}), 404
        existing = qr.data[0]
        data = request.get_json(silent=True) or {}
        upd = {}
        if 'status' in data:
            st = str(data.get('status') or '').strip().lower()
            if st not in QUOTE_STATUSES:
                return jsonify({'error': 'Invalid status'}), 400
            upd['status'] = st
        if 'quote_payload' in data:
            if str(existing.get('status') or '').lower() != 'draft':
                return jsonify({'error': 'Only draft quotes can be edited'}), 400
            qp = leads.safe_json(data.get('quote_payload'), {})
            if not isinstance(qp, dict):
                return jsonify({'error': 'quote_payload must be an object'}), 400
            upd['quote_payload'] = qp
        if not upd:
            return jsonify({'error': 'Nothing to update'}), 400
        upd['updated_at'] = datetime.utcnow().isoformat()
        sb.table('crm_deal_quotes').update(upd).eq('id', str(quote_id)).execute()
        crm_cache_bump()
        return jsonify({'success': True})

    @app.route('/api/crm/deals/<deal_id>/quotation/<quote_id>', methods=['GET'])
    def open_deal_quote(deal_id, quote_id):
        sb = get_supabase()
        if not sb:
            return Response('Database not configured', status=503)
        token = str(request.args.get('token') or '').strip()
        if not token:
            return Response('Missing token', status=400)
        try:
            qr = (
                sb.table('crm_deal_quotes')
                .select('id, deal_id, quote_payload, share_token')
                .eq('id', str(quote_id))
                .eq('deal_id', str(deal_id))
                .eq('share_token', token)
                .limit(1)
                .execute()
            )
            if not qr.data:
                return Response('Invalid or expired quote link', status=404)
            payload = leads.safe_json((qr.data[0] or {}).get('quote_payload'), {})
            deal = leads.safe_json(payload.get('deal'), {})
            contact = leads.safe_json(payload.get('contact'), {})
            inputs = leads.safe_json(payload.get('inputs'), {})
            plots = leads.safe_json(deal.get('plots'), [])

            # quote_payload is user-authored JSON served on an unauthenticated
            # page, so every value must be HTML-escaped before interpolation.
            def _q(value):
                return escape(str(value if value is not None else ''))

            plot_rows = ''.join([
                '<tr>'
                f"<td>{idx + 1}</td>"
                f"<td>{_q((p or {}).get('name') or '')}</td>"
                f"<td>{_q((p or {}).get('area') or '')}</td>"
                f"<td>{_q((p or {}).get('price') or '')}</td>"
                '</tr>'
                for idx, p in enumerate(plots if isinstance(plots, list) else [])
            ]) or '<tr><td colspan="4">No plots</td></tr>'
            html = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quotation</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; color:#111827; }}
.card {{ border:1px solid #e5e7eb; border-radius:10px; padding:16px; margin-bottom:16px; }}
table {{ width:100%; border-collapse: collapse; }}
th,td {{ border:1px solid #e5e7eb; padding:8px; text-align:left; }}
h1 {{ margin:0 0 8px; font-size:22px; }}
.muted {{ color:#6b7280; }}
</style></head><body>
<h1>Quotation</h1>
<div class="card">
<div><strong>Deal:</strong> {_q(deal.get('title') or '')}</div>
<div><strong>Project:</strong> {_q(deal.get('project_name') or '')}</div>
<div><strong>Stage:</strong> {_q(deal.get('stage') or '')}</div>
<div><strong>Amount:</strong> {_q(deal.get('amount') or '')} {_q(deal.get('currency') or '')}</div>
</div>
<div class="card">
<div><strong>Contact:</strong> {_q(contact.get('full_name') or '')}</div>
<div><strong>Email:</strong> {_q(contact.get('email') or '')}</div>
<div><strong>Phone:</strong> {_q(contact.get('phone') or '')}</div>
</div>
<div class="card">
<div class="muted">Quote Inputs</div>
<pre>{_q(json.dumps(inputs, indent=2))}</pre>
</div>
<div class="card">
<table><thead><tr><th>#</th><th>Plot</th><th>Area</th><th>Price</th></tr></thead>
<tbody>{plot_rows}</tbody></table>
</div>
</body></html>"""
            return Response(html, mimetype='text/html')
        except Exception as e:
            return Response(str(e), status=500, mimetype='text/plain')
