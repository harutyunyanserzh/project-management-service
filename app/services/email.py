import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    """Send an email via SMTP.

    If SMTP_HOST is not configured (the default in development), the message
    is logged instead of sent. This keeps the share flow fully usable and
    testable locally without requiring a real mail account -- the join link
    simply appears in the application logs.
    """
    if not settings.SMTP_HOST:
        logger.warning(
            "SMTP not configured; email not sent. to=%s subject=%s\n%s", to, subject, body
        )
        return

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(message)

    logger.info("Sent email to %s (subject=%s)", to, subject)
