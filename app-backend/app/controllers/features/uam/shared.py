from datetime import datetime
from html import escape

from flask import jsonify, request

from app import config as app_config
from app.core.auth import get_profile
from app.services.email_service import send_email as send_smtp_email
from app.services.uam_reference_service import (
    CLIENT_MEMBER_ALLOWED_ROLES,
    CLIENT_MEMBER_BROKER_ROLES,
    CLIENT_MEMBER_CLIENT_ADMIN_ACCESS_TARGET_ROLES,
    CLIENT_MEMBER_GROUP_ACCESS_ROLES,
    CLIENT_MEMBER_REFERENCE_ROLE_LABELS,
    CLIENT_MEMBER_REFERENCE_ROLES,
    CLIENT_MEMBER_ROLE_ALIASES,
    CLIENT_MEMBER_ROLE_BROKER,
    CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
    CLIENT_MEMBER_ROLE_CLIENT_USER,
    _is_broker_member_role,
    _normalize_client_member_role,
    _project_reference_client_ids,
    _project_reference_users,
    _validate_project_reference_user,
)

DEFAULT_CLIENT_MEMBERS_ALLOWED = 10
MAX_CLIENT_MEMBERS_ALLOWED = 100000


def _normalize_client_members_allowed(value, default=DEFAULT_CLIENT_MEMBERS_ALLOWED):
    if value is None or value == '':
        return int(default)
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise ValueError('Members allowed must be a whole number')
    if normalized < 1:
        raise ValueError('Members allowed must be at least 1')
    if normalized > MAX_CLIENT_MEMBERS_ALLOWED:
        raise ValueError(f'Members allowed cannot exceed {MAX_CLIENT_MEMBERS_ALLOWED}')
    return normalized


def _client_member_limit_message(members_allowed):
    return f'Restricted to {int(members_allowed)} users. Contact Admin to Unlock More'


def _is_active_pending_client_invite(row):
    if str((row or {}).get('status') or '').strip().lower() != 'pending':
        return False
    expires_at = (row or {}).get('expires_at')
    if not expires_at:
        return True
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace('Z', '+00:00'))
        now = datetime.utcnow().replace(tzinfo=expiry.tzinfo)
        return now <= expiry
    except Exception:
        return True


def _client_capacity_snapshot(sb, client_id, client=None):
    client_row = client
    if not client_row:
        result = (
            sb.table('clients')
            .select('id, members_allowed')
            .eq('id', str(client_id))
            .limit(1)
            .execute()
        )
        client_row = (result.data or [None])[0]
    if not client_row:
        return None

    members_allowed = _normalize_client_members_allowed(
        client_row.get('members_allowed'),
        DEFAULT_CLIENT_MEMBERS_ALLOWED,
    )
    members = (
        sb.table('client_members')
        .select('id')
        .eq('client_id', str(client_id))
        .execute()
    )
    invites = (
        sb.table('client_team_invites')
        .select('id, status, expires_at')
        .eq('client_id', str(client_id))
        .eq('status', 'pending')
        .execute()
    )
    member_count = len(members.data or [])
    pending_invite_count = sum(
        1 for row in (invites.data or []) if _is_active_pending_client_invite(row)
    )
    occupied_count = member_count + pending_invite_count
    return {
        'members_allowed': members_allowed,
        'member_count': member_count,
        'pending_invite_count': pending_invite_count,
        'occupied_count': occupied_count,
        'remaining_slots': max(0, members_allowed - occupied_count),
        'at_capacity': occupied_count >= members_allowed,
    }



def _get_caller_org_id(sb, user_id):
    """Return the org_id for the calling user, or None."""
    profile = get_profile(sb, user_id) or {}
    return profile.get('org_id')

def _is_target_admin(sb, target_user_id):
    """Check if a target user is admin or superadmin."""
    target = get_profile(sb, target_user_id) or {}
    return target.get('role') in ('admin', 'superadmin')

def _can_manage_target(sb, caller_id, caller_role, target_user_id):
    """
    Returns (ok, error_msg, status_code).
    Admin cannot modify another admin. Superadmin can manage anyone.
    Both must share the same org (unless superadmin).
    """
    caller_profile = get_profile(sb, caller_id) or {}
    caller_org = caller_profile.get('org_id')
    if not caller_org:
        return False, 'Your organization is not set', 403

    target_profile = get_profile(sb, target_user_id) or {}
    target_org = target_profile.get('org_id')
    target_role = target_profile.get('role', 'user')

    if caller_role != 'superadmin':
        if not target_org or str(target_org) != str(caller_org):
            return False, 'User is not in your organization', 403
        if target_role in ('admin', 'superadmin'):
            return False, 'You cannot modify another admin user', 403
        if str(target_user_id) == str(caller_id):
            return False, 'You cannot modify your own account here', 403
    return True, None, None

def _get_client_org(sb, client_id, caller_id, caller_role):
    """Return (client_row, error_response). Verifies org boundary."""
    try:
        r = sb.table('clients').select('*').eq('id', client_id).limit(1).execute()
    except Exception as e:
        return None, (jsonify({'error': str(e)}), 500)
    if not r.data:
        return None, (jsonify({'error': 'Client group not found'}), 404)
    client = r.data[0]
    if caller_role != 'superadmin':
        caller_org = _get_caller_org_id(sb, caller_id)
        if not caller_org or str(client.get('org_id')) != str(caller_org):
            return None, (jsonify({'error': 'Forbidden'}), 403)
    return client, None


def _get_client_member_rows(sb, client_id):
    rows = sb.table('client_members').select('id, user_id, member_role').eq('client_id', str(client_id)).execute()
    out = []
    for row in (rows.data or []):
        normalized_role = _normalize_client_member_role(row.get('member_role'))
        out.append({
            'id': row.get('id'),
            'user_id': str(row.get('user_id') or ''),
            'member_role': normalized_role,
            'raw_member_role': row.get('member_role'),
        })
    return out

def _get_client_member_row(sb, client_id, member_user_id):
    try:
        rows = _get_client_member_rows(sb, client_id)
        member_user_id = str(member_user_id or '')
        for row in rows:
            if str(row.get('user_id') or '') == member_user_id:
                return row
    except Exception:
        return None
    return None


def _resource_exists_for_client_access(sb, resource_type, resource_id):
    try:
        if resource_type == 'workspace':
            r = sb.table('workspaces').select('id').eq('id', str(resource_id)).limit(1).execute()
        else:
            r = sb.table('panoramas').select('id').eq('id', int(resource_id)).limit(1).execute()
        return bool(r.data and len(r.data) > 0)
    except Exception:
        return False

def _client_admin_has_resource_in_group_scope(sb, actor_member_id, actor_user_id, resource_type, resource_id):
    try:
        if resource_type == 'workspace':
            r = (
                sb.table('workspace_access')
                .select('id')
                .eq('workspace_id', str(resource_id))
                .eq('user_id', str(actor_user_id))
                .eq('client_member_id', actor_member_id)
                .limit(1)
                .execute()
            )
        else:
            r = (
                sb.table('panorama_access')
                .select('id')
                .eq('panorama_id', int(resource_id))
                .eq('user_id', str(actor_user_id))
                .eq('client_member_id', actor_member_id)
                .limit(1)
                .execute()
            )
        return bool(r.data and len(r.data) > 0)
    except Exception:
        return False

def _resource_exists_in_client_member_scope(sb, resource_type, resource_id, member_ids):
    try:
        scoped_member_ids = [mid for mid in (member_ids or []) if mid]
        if not scoped_member_ids:
            return False
        if resource_type == 'workspace':
            r = (
                sb.table('workspace_access')
                .select('id')
                .eq('workspace_id', str(resource_id))
                .in_('client_member_id', scoped_member_ids)
                .limit(1)
                .execute()
            )
        else:
            r = (
                sb.table('panorama_access')
                .select('id')
                .eq('panorama_id', int(resource_id))
                .in_('client_member_id', scoped_member_ids)
                .limit(1)
                .execute()
            )
        return bool(r.data and len(r.data) > 0)
    except Exception:
        return False

def _is_client_admin_of(sb, user_id, client_id):
    """Check if user is a client_admin in the given client group."""
    try:
        r = sb.table('client_members').select('id').eq('client_id', client_id).eq('user_id', user_id).eq('member_role', 'client_admin').limit(1).execute()
        return bool(r.data and len(r.data) > 0)
    except Exception:
        return False

def _project_access_type_for_member_role(access_type, member_role):
    normalized_role = _normalize_client_member_role(member_role)
    if normalized_role in CLIENT_MEMBER_BROKER_ROLES:
        return 'broker'
    normalized_access = str(access_type or 'client').strip().lower()
    return normalized_access if normalized_access in ('client', 'broker', 'viewer') else 'client'

def _build_client_team_invite_link(invite_token):
    base = (request.url_root or '').rstrip('/')
    return f"{base}/client-invite/{invite_token}"

def _send_client_team_invite_email(to_email, inviter_name, client_name, invite_link):
    subject = f"{inviter_name} invited you to join {client_name}"
    body = (
        f"Hi,\n\n"
        f"{inviter_name} has invited you to join his team {client_name}.\n\n"
        f"Accept invitation:\n{invite_link}\n\n"
        f"If you don't have an account yet, sign up with this same email and the invite will be applied automatically.\n"
        f"If you already have an account, sign in and accept.\n\n"
        f"Regards,\nMarketoState"
    )
    inviter_name_html = escape(str(inviter_name or "A teammate"))
    client_name_html = escape(str(client_name or "Team"))
    invite_link_html = escape(str(invite_link or ""))
    html_body = f"""<!doctype html>
<html>
  <head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Team Invite</title>
  </head>
  <body style="margin:0;padding:0;background:#f3f5f9;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f3f5f9;padding:24px 12px;">
  <tr>
    <td align="center">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:620px;background:#ffffff;border:1px solid #e5eaf2;border-radius:16px;overflow:hidden;">
        <tr>
          <td style="padding:24px 28px;background:linear-gradient(135deg,#0f172a,#1e293b);color:#ffffff;">
            <div style="font-size:13px;letter-spacing:0.08em;text-transform:uppercase;opacity:0.86;">MarketoState</div>
            <h1 style="margin:10px 0 0 0;font-size:24px;line-height:1.3;font-weight:700;">You are invited to join a client team</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:26px 28px 18px 28px;color:#0f172a;font-family:Arial,Helvetica,sans-serif;">
            <p style="margin:0 0 14px 0;font-size:15px;line-height:1.7;">
              <strong>{inviter_name_html}</strong> has invited you to join team
              <strong>{client_name_html}</strong>.
            </p>
            <p style="margin:0 0 18px 0;font-size:14px;line-height:1.7;color:#334155;">
              Use the button below to accept this invitation. If you already have an account, sign in. If not, sign up with this same email and you will be added automatically.
            </p>
            <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 18px 0;">
              <tr>
                <td align="center" bgcolor="#0f172a" style="border-radius:10px;">
                  <a href="{invite_link_html}" style="display:inline-block;padding:12px 20px;font-size:14px;font-weight:700;line-height:1;color:#ffffff;text-decoration:none;border-radius:10px;">
                    Accept Invitation
                  </a>
                </td>
              </tr>
            </table>
            <div style="margin:0 0 4px 0;font-size:12px;color:#64748b;">Button not working? Copy and paste this link in your browser:</div>
            <div style="font-size:12px;word-break:break-all;color:#1d4ed8;">
              <a href="{invite_link_html}" style="color:#1d4ed8;text-decoration:none;">{invite_link_html}</a>
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 28px 24px 28px;border-top:1px solid #e5eaf2;color:#64748b;font-size:12px;font-family:Arial,Helvetica,sans-serif;">
            This invitation was sent by MarketoState.
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
  </body>
</html>"""
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
        html_body=html_body,
        brevo_api_key=app_config.BREVO_API_KEY,
    )

def _accept_client_team_invite_token(sb, token, user_id):
    token = (token or '').strip()
    if not token:
        return False, 'Invite token is required', 400

    ir = (
        sb.table('client_team_invites')
        .select('*')
        .eq('invite_token', token)
        .limit(1)
        .execute()
    )
    invite = (ir.data or [None])[0]
    if not invite:
        return False, 'Invite not found', 404

    client_id = str(invite.get('client_id') or '')
    member_role = _normalize_client_member_role(invite.get('member_role')) or CLIENT_MEMBER_ROLE_CLIENT_USER
    if member_role not in (
        CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
        CLIENT_MEMBER_ROLE_CLIENT_USER,
        CLIENT_MEMBER_ROLE_BROKER,
    ):
        member_role = CLIENT_MEMBER_ROLE_CLIENT_USER

    # Validate email ownership to prevent token misuse
    profile = get_profile(sb, user_id) or {}
    session_email = str(profile.get('email') or '').strip().lower()
    invite_email = str(invite.get('email') or '').strip().lower()
    if session_email and invite_email and session_email != invite_email:
        # If email mismatch, still allow if user is already a member of this client
        if client_id:
            existing_member = (
                sb.table('client_members')
                .select('id, member_role')
                .eq('client_id', client_id)
                .eq('user_id', str(user_id))
                .limit(1)
                .execute()
            )
            if existing_member.data:
                member_row = existing_member.data[0]
                return True, {
                    'client_id': client_id,
                    'member_role': member_row.get('member_role') or member_role,
                    'member_id': member_row.get('id'),
                    'already_member': True,
                }, 200
        return False, 'This invite belongs to a different email address', 403

    status = str(invite.get('status') or '').lower()

    # If invite is not active, check if user is already a member — let them log in gracefully
    if status not in ('pending', 'accepted'):
        if client_id:
            existing_member = (
                sb.table('client_members')
                .select('id, member_role')
                .eq('client_id', client_id)
                .eq('user_id', str(user_id))
                .limit(1)
                .execute()
            )
            if existing_member.data:
                member_row = existing_member.data[0]
                return True, {
                    'client_id': client_id,
                    'member_role': member_row.get('member_role') or member_role,
                    'member_id': member_row.get('id'),
                    'already_member': True,
                }, 200
        return False, 'Invite is not active', 400

    expires_at = invite.get('expires_at')
    if expires_at:
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace('Z', '+00:00'))
            now = datetime.utcnow().replace(tzinfo=expiry.tzinfo)
            if now > expiry:
                try:
                    sb.table('client_team_invites').update({'status': 'expired', 'updated_at': datetime.utcnow().isoformat()}).eq('id', invite.get('id')).execute()
                except Exception:
                    pass
                # Even if expired, let existing members log in gracefully
                if client_id:
                    existing_member = (
                        sb.table('client_members')
                        .select('id, member_role')
                        .eq('client_id', client_id)
                        .eq('user_id', str(user_id))
                        .limit(1)
                        .execute()
                    )
                    if existing_member.data:
                        member_row = existing_member.data[0]
                        return True, {
                            'client_id': client_id,
                            'member_role': member_row.get('member_role') or member_role,
                            'member_id': member_row.get('id'),
                            'already_member': True,
                        }, 200
                return False, 'Invite has expired', 400
        except Exception:
            pass

    if not client_id:
        return False, 'Invalid invite', 400

    # Already a member -> just mark accepted
    existing_member = (
        sb.table('client_members')
        .select('id, member_role')
        .eq('client_id', client_id)
        .eq('user_id', str(user_id))
        .limit(1)
        .execute()
    )
    member_id = None
    if existing_member.data:
        member_row = existing_member.data[0]
        member_id = member_row.get('id')
        current_role = _normalize_client_member_role(member_row.get('member_role')) or CLIENT_MEMBER_ROLE_CLIENT_USER
        if member_id and current_role != member_role:
            sb.table('client_members').update({
                'member_role': member_role,
                'invited_by': invite.get('invited_by'),
            }).eq('id', member_id).execute()
    else:
        capacity = _client_capacity_snapshot(sb, client_id)
        if not capacity:
            return False, 'Client group not found', 404
        limit_reached = (
            capacity['occupied_count'] > capacity['members_allowed']
            if status == 'pending'
            else capacity['at_capacity']
        )
        if limit_reached:
            return False, _client_member_limit_message(capacity['members_allowed']), 409
        ins = (
            sb.table('client_members')
            .insert({
                'client_id': client_id,
                'user_id': str(user_id),
                'member_role': member_role,
                'invited_by': invite.get('invited_by'),
            })
            .execute()
        )
        member = (ins.data or [None])[0]
        member_id = member.get('id') if member else None
        if member_id:
            _cascade_access_for_new_member(sb, client_id, member_id, user_id, member_role, invite.get('invited_by') or user_id)
            _propagate_new_member_access_to_group(sb, client_id, member_id, user_id, member_role, invite.get('invited_by') or user_id)

    # Ensure profile org is linked
    try:
        org_id = invite.get('org_id')
        if org_id:
            sb.table('profiles').update({'org_id': str(org_id), 'updated_at': datetime.utcnow().isoformat()}).eq('user_id', str(user_id)).execute()
    except Exception:
        pass

    sb.table('client_team_invites').update({
        'status': 'accepted',
        'accepted_at': datetime.utcnow().isoformat(),
        'accepted_user_id': str(user_id),
        'updated_at': datetime.utcnow().isoformat(),
    }).eq('id', invite.get('id')).execute()

    return True, {
        'client_id': client_id,
        'member_role': member_role,
        'member_id': member_id,
    }, 200

def _propagate_new_member_access_to_group(sb, client_id, new_member_id, new_user_id, member_role, granter_id):
    """When a new member with existing project access joins a group, grant those projects to all existing group members."""
    normalized_member_role = _normalize_client_member_role(member_role)
    if normalized_member_role not in (
        CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
        CLIENT_MEMBER_ROLE_CLIENT_USER,
        CLIENT_MEMBER_ROLE_BROKER,
    ):
        return
    try:
        # Get new user's existing panorama_access (all rows, not just client-tagged)
        pa = sb.table('panorama_access').select('panorama_id, access_type').eq('user_id', str(new_user_id)).execute()
        ws_a = sb.table('workspace_access').select('workspace_id, access_type').eq('user_id', str(new_user_id)).execute()
        pano_rows = [(r.get('panorama_id'), r.get('access_type', 'client')) for r in (pa.data or []) if r.get('panorama_id')]
        ws_rows = [(r.get('workspace_id'), r.get('access_type', 'client')) for r in (ws_a.data or []) if r.get('workspace_id')]
        if not pano_rows and not ws_rows:
            return
        # Get all existing members (excluding the new one) with their client_member_id and user_id
        existing = sb.table('client_members').select('id, user_id, member_role').eq('client_id', client_id).neq('id', new_member_id).execute()
        siblings = [
            (r.get('id'), str(r.get('user_id') or ''), _normalize_client_member_role(r.get('member_role')))
            for r in (existing.data or [])
            if r.get('id') and r.get('user_id')
        ]
        # Also include the new member themselves (tag their own access with client_member_id)
        siblings.append((new_member_id, str(new_user_id), normalized_member_role))
        for (mid, uid, mrole) in siblings:
            if mrole not in (
                CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
                CLIENT_MEMBER_ROLE_CLIENT_USER,
                CLIENT_MEMBER_ROLE_BROKER,
            ):
                continue
            for (pid, atype) in pano_rows:
                if str(uid) == str(new_user_id):
                    # New member: update their existing row to tag with client_member_id
                    pass  # their personal row stays as-is; we don't overwrite it
                try:
                    member_access_type = _project_access_type_for_member_role(atype, mrole)
                    sb.table('panorama_access').upsert({
                        'panorama_id': pid, 'user_id': str(uid),
                        'access_type': member_access_type, 'granted_by': str(granter_id),
                        'client_member_id': mid,
                    }, on_conflict='panorama_id,user_id').execute()
                except Exception:
                    pass
            for (wsid, atype) in ws_rows:
                try:
                    member_access_type = _project_access_type_for_member_role(atype, mrole)
                    sb.table('workspace_access').upsert({
                        'workspace_id': str(wsid), 'user_id': str(uid),
                        'access_type': member_access_type, 'granted_by': str(granter_id),
                        'client_member_id': mid,
                    }, on_conflict='workspace_id,user_id').execute()
                except Exception:
                    pass
    except Exception:
        pass

def _cascade_access_for_new_member(sb, client_id, new_member_id, new_user_id, member_role, granter_id):
    """When adding an internal client-group member, grant access to resources already accessible to this client group."""
    normalized_member_role = _normalize_client_member_role(member_role)
    if normalized_member_role not in (
        CLIENT_MEMBER_ROLE_CLIENT_ADMIN,
        CLIENT_MEMBER_ROLE_CLIENT_USER,
        CLIENT_MEMBER_ROLE_BROKER,
    ):
        return
    try:
        existing = sb.table('client_members').select('id').eq('client_id', client_id).neq('id', new_member_id).execute()
        sibling_ids = [r.get('id') for r in (existing.data or []) if r.get('id')]
        if not sibling_ids:
            return
        pa = sb.table('panorama_access').select('panorama_id, access_type').in_('client_member_id', sibling_ids).execute()
        seen_pano = set()
        for row in (pa.data or []):
            pid = row.get('panorama_id')
            if pid in seen_pano:
                continue
            seen_pano.add(pid)
            try:
                member_access_type = _project_access_type_for_member_role(row.get('access_type', 'client'), normalized_member_role)
                sb.table('panorama_access').upsert({
                    'panorama_id': pid, 'user_id': str(new_user_id),
                    'access_type': member_access_type,
                    'granted_by': str(granter_id), 'client_member_id': new_member_id,
                }, on_conflict='panorama_id,user_id').execute()
            except Exception:
                pass
        wa = sb.table('workspace_access').select('workspace_id, access_type').in_('client_member_id', sibling_ids).execute()
        seen_ws = set()
        for row in (wa.data or []):
            wsid = row.get('workspace_id')
            if wsid in seen_ws:
                continue
            seen_ws.add(wsid)
            try:
                member_access_type = _project_access_type_for_member_role(row.get('access_type', 'client'), normalized_member_role)
                sb.table('workspace_access').upsert({
                    'workspace_id': str(wsid), 'user_id': str(new_user_id),
                    'access_type': member_access_type,
                    'granted_by': str(granter_id), 'client_member_id': new_member_id,
                }, on_conflict='workspace_id,user_id').execute()
            except Exception:
                pass
    except Exception:
        pass
