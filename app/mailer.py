"""Outgoing email.

If SMTP settings are present in the environment, real emails are sent.
Otherwise the app runs in demo mode: the email is printed to the server
console instead, so the system can be evaluated without a mail server.

    SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM
"""
import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("intrinsic.mail")


def smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST"))


def send_email(to: str, subject: str, body: str, html: str | None = None) -> bool:
    """Send an email. Returns True if it was really sent, False in demo mode."""
    if not smtp_configured():
        print(f"\n[DEMO EMAIL] To: {to}\nSubject: {subject}\n{body}\n", flush=True)
        return False

    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "no-reply@intrinsic.local"))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=15) as smtp:
        smtp.starttls()
        if os.getenv("SMTP_USER"):
            smtp.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(msg)
    log.info("Email sent to %s: %s", to, subject)
    return True
