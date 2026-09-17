"""Minimal SMTP email sender for transactional notifications."""

from email.message import EmailMessage
import smtplib
import json
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError


def send_email(
    smtp_host,
    smtp_port,
    smtp_username,
    smtp_password,
    smtp_use_tls,
    from_email,
    from_name,
    to_email,
    subject,
    text_body,
    html_body=None,
    brevo_api_key=None,
):
    resolved_to_email = str(to_email or "").strip()
    resolved_from_email = str(from_email or "").strip()
    smtp_user_email = str(smtp_username or "").strip()
    if not resolved_from_email and "@" in smtp_user_email and " " not in smtp_user_email:
        resolved_from_email = smtp_user_email
    if not resolved_to_email:
        raise ValueError("to_email is required")
    if not resolved_from_email:
        raise ValueError("from_email is required (set SMTP_FROM_EMAIL or a valid SMTP_USERNAME)")

    # Prefer Brevo API when key is configured.
    if brevo_api_key:
        payload = {
            "sender": {"name": from_name or "", "email": resolved_from_email},
            "to": [{"email": resolved_to_email}],
            "subject": subject or "",
            "textContent": text_body or "",
        }
        if html_body:
            payload["htmlContent"] = html_body
        body_bytes = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            "https://api.brevo.com/v3/smtp/email",
            data=body_bytes,
            method="POST",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "api-key": brevo_api_key,
            },
        )
        try:
            with urlrequest.urlopen(req, timeout=20) as resp:
                if resp.status >= 300:
                    raise RuntimeError(f"Brevo API failed with status {resp.status}")
            return
        except HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="ignore")
            except Exception:
                detail = str(e)
            raise RuntimeError(f"Brevo API error: {e.code} {detail}") from e
        except URLError as e:
            raise RuntimeError(f"Brevo API connection error: {e}") from e

    if not smtp_host:
        raise ValueError("SMTP is not configured")

    # Fallback to SMTP when Brevo API key is not configured.
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{resolved_from_email}>" if from_name else resolved_from_email
    msg["To"] = resolved_to_email
    msg.set_content(text_body or "")
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(smtp_host, int(smtp_port), timeout=20) as server:
        if smtp_use_tls:
            server.starttls()
        if smtp_username:
            server.login(smtp_username, smtp_password or "")
        server.send_message(msg)
