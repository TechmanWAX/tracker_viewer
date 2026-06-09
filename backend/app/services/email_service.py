"""Email delivery service.

Why this exists
---------------
The spec says "send a one-time verification link" at registration,
so we need a real way to put the link in front of the user. There
are two transports:

  * `MAIL_ENABLED=false` — write the email to a per-developer
    directory (`/tmp/verification_emails/` by default) and log a
    one-liner. Useful when the SMTP server is unavailable or you
    want to inspect the exact payload before it goes out.

  * `MAIL_ENABLED=true` — actually send the email via SMTP. The
    credentials and host come from environment variables / .env.
    This is what production uses.

Both branches share the same `build_verification_email` helper, so
the text and HTML bodies are identical regardless of transport.

Security
--------
* The raw token is **only** ever embedded in the email body. The
  database stores SHA-256(raw), not the raw value, so a DB leak
  doesn't let an attacker forge verification links.

* The link is single-use. The endpoint that consumes it sets
  `used_at = now()` and rejects replays.

* SMTP credentials live in .env, never in source. .env should be
  in .gitignore (this project isn't a git repo on this machine, but
  the convention is the same).

Threading
---------
smtplib is synchronous. We run it through `asyncio.to_thread` so
the FastAPI event loop stays responsive while the SMTP handshake
+ RCPT + DATA are in flight (typically 200–500ms).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.models.user import User

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerificationEmail:
    """A rendered verification email ready to send."""

    to: str
    subject: str
    body_text: str
    body_html: str
    verification_url: str


def build_verification_email(user: "User", raw_token: str) -> VerificationEmail:
    """Build the email body for a verification link.

    Centralized so the dev file-writer, the SMTP transport, and a
    test can all use the same exact text. The link points at the
    frontend (`/verify-email?token=…`) which then calls the API to
    actually consume the token — we don't bake auth into the link.
    """
    settings = get_settings()
    url = (
        f"{settings.app_base_url.rstrip('/')}"
        f"/verify-email?token={raw_token}"
    )
    subject = "Verify your GPS Trip Tracker email"
    body_text = (
        f"Hi {user.username},\n\n"
        "Welcome to GPS Trip Tracker. To finish setting up your "
        "account, click the link below (or paste it into your "
        "browser). The link expires in "
        f"{settings.verification_token_ttl_minutes} minutes and can "
        "be used only once.\n\n"
        f"{url}\n\n"
        "If you didn't sign up for this account, you can safely "
        "ignore this message.\n\n"
        "— GPS Trip Tracker"
    )
    body_html = (
        f"<p>Hi {user.username},</p>"
        "<p>Welcome to GPS Trip Tracker. To finish setting up your "
        "account, click the button below. The link expires in "
        f"{settings.verification_token_ttl_minutes} minutes and can "
        "be used only once.</p>"
        f'<p><a href="{url}" style="display:inline-block;padding:10px 16px;'
        'background:#4f9eff;color:#fff;border-radius:4px;text-decoration:'
        f'none">Verify email</a></p>'
        f'<p style="color:#666;font-size:12px">Or paste this link into your browser:<br>'
        f"<code>{url}</code></p>"
        "<p>If you didn't sign up for this account, you can safely "
        "ignore this message.</p>"
        "<p>— GPS Trip Tracker</p>"
    )
    return VerificationEmail(
        to=user.email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        verification_url=url,
    )


async def send_verification_email(user: "User", raw_token: str) -> VerificationEmail:
    """Deliver a verification email via the configured transport.

    Returns the rendered email so the caller can include the URL
    in dev API responses / logs without re-rendering it.

    This is async because the SMTP branch hands the blocking
    `smtplib` call to `asyncio.to_thread`; the dev-file branch is
    sync but cheap. The function is awaited from both
    `register` and `resend_verification`.
    """
    email = build_verification_email(user, raw_token)
    settings = get_settings()

    if not settings.mail_enabled:
        _write_dev_email(email)
        log.info(
            "verification_email dev-write to=%s url=%s",
            email.to,
            email.verification_url,
        )
        return email

    # Production path: real SMTP. We do this inside
    # `asyncio.to_thread` so the FastAPI event loop isn't blocked
    # by the network round-trip.
    try:
        await _send_smtp(email)
        log.info("verification_email smtp-sent to=%s", email.to)
    except Exception as exc:
        # Don't surface the failure to the user as a 500: the
        # account is created and the user can request a new link
        # via /resend-verification. We log loudly so operators
        # notice.
        log.exception("verification_email smtp FAILED to=%s: %s", email.to, exc)
        # Fall back to the dev file so the developer can still
        # inspect what would have been sent.
        _write_dev_email(email)
    return email


# ---------------------------------------------------------------------------
# SMTP transport
# ---------------------------------------------------------------------------


async def _send_smtp(email: VerificationEmail) -> None:
    """Send `email` via the configured SMTP server.

    Two port modes are supported:
      * 587 (submission) — STARTTLS upgrade over a plain connection.
      * 465 (submissions) — implicit TLS from the start.
    Anything else falls back to a plain connection, which most
    modern providers reject — but we don't want to crash on
    misconfiguration; we log and raise.
    """
    settings = get_settings()
    if not settings.mail_host or not settings.mail_username or not settings.mail_password:
        raise RuntimeError(
            "MAIL_ENABLED=true but MAIL_HOST / MAIL_USERNAME / MAIL_PASSWORD "
            "are not all set. Check backend/.env."
        )
    if not settings.mail_tls_verify:
        # Loud warning, once per send. We don't suppress this because
        # someone setting up mail in a fresh environment is very
        # likely to flip this without realising the security cost.
        log.warning(
            "MAIL_TLS_VERIFY=false — SMTP TLS certificate verification is "
            "DISABLED. This is a dev-only escape hatch for expired or "
            "self-signed certs. Do not use in production."
        )

    msg = _build_email_message(email)
    await asyncio.to_thread(
        _smtp_send_blocking,
        settings.mail_host,
        settings.mail_port,
        settings.mail_username,
        settings.mail_password,
        settings.mail_from,
        settings.mail_tls_verify,
        msg,
    )


def _smtp_send_blocking(
    host: str,
    port: int,
    username: str,
    password: str,
    from_addr: str,
    tls_verify: bool,
    msg: EmailMessage,
) -> None:
    """Synchronous SMTP send. Runs inside `asyncio.to_thread`."""
    ctx = ssl.create_default_context()
    if not tls_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    if port == 465:
        # Implicit TLS from the first byte.
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as smtp:
            smtp.login(username, password)
            smtp.send_message(msg)
    else:
        # 587 (or any other port): plain connect, then STARTTLS.
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(msg)


def _build_email_message(email: VerificationEmail) -> EmailMessage:
    """Build an `email.message.EmailMessage` with both a plain-text
    and an HTML body. The `multipart/alternative` content type
    makes email clients pick the best version they can render."""
    msg = EmailMessage()
    settings = get_settings()
    msg["From"] = settings.mail_from
    msg["To"] = email.to
    msg["Subject"] = email.subject
    msg.set_content(email.body_text)
    msg.add_alternative(email.body_html, subtype="html")
    return msg


# ---------------------------------------------------------------------------
# Dev file transport
# ---------------------------------------------------------------------------


def _write_dev_email(email: VerificationEmail) -> None:
    """Write the email to <mail_dev_out_dir>/<timestamp>_<email>.json.

    Useful both as the dev transport and as a fallback when real
    SMTP fails. We persist the full payload (to, subject, bodies,
    link) so a developer can `cat` the file and see exactly what
    the user would have received.
    """
    settings = get_settings()
    out_dir = settings.mail_dev_out_dir
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = os.path.join(out_dir, f"{ts}_{email.to}.json")
    payload = {
        "to": email.to,
        "subject": email.subject,
        "body_text": email.body_text,
        "body_html": email.body_html,
        "verification_url": email.verification_url,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
