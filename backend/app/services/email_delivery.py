"""Minimal SMTP delivery for job-alert digests.

Email is entirely optional: when ``EMAIL_ALERTS_ENABLED`` is false or no
``SMTP_HOST`` is configured, ``send_email`` returns a ``disabled`` result and
the caller keeps the in-app notification as the delivery channel.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

log = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 20


def email_configured() -> bool:
    settings = get_settings()
    return bool(settings.email_alerts_enabled and settings.smtp_host.strip())


def send_email(
    to_address: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> tuple[str, str | None]:
    """Send one email.

    Returns ``(status, error)`` where status is one of ``sent``, ``disabled``
    or ``failed``.  Never raises — alert delivery must not break the worker.
    """
    settings = get_settings()
    if not email_configured():
        return "disabled", None
    if not to_address or "@" not in to_address:
        return "failed", "recipient address is invalid"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.email_from
    message["To"] = to_address
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.ehlo()
            if settings.smtp_use_tls:
                smtp.starttls()
                smtp.ehlo()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return "sent", None
    except Exception as exc:  # noqa: BLE001 - delivery failures are reported, not raised
        log.exception("job-alert email delivery failed")
        return "failed", str(exc)
