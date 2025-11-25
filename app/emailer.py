# Example emailer module using aiosmtplib (async). The Celery worker tasks can call a synchronous wrapper
# or use asyncio.run(...) if tasks are sync. For real Celery workers with asyncio support, adapt accordingly.

import os
import asyncio
from email.message import EmailMessage
import aiosmtplib

SMTP_HOST = os.getenv("SMTP_HOST", "mailhog")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "false").lower() in ("1", "true", "yes")
MAIL_TRANSPORT = os.getenv("MAIL_TRANSPORT", "mailhog").lower()

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "anandcelestis@gmail.com")

async def send_email_async(subject: str, html_body: str, to_email: str, from_email: str = "no-reply@example.com"):
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content("This client supports HTML. See HTML part.")
    msg.add_alternative(html_body, subtype="html")

    # MailHog is just a regular SMTP server on the given host:port
    try:
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER or None,
            password=SMTP_PASSWORD or None,
            start_tls=SMTP_USE_TLS,
        )
        return {"status": "sent", "error": None}
    except aiosmtplib.errors.SMTPException as e:
        return {"status": "failed", "error": str(e)}
    except Exception as e:  # handle network and unexpected errors
        return {"status": "failed", "error": str(e)}

def send_email(subject: str, html_body: str, to_email: str, from_email: str = "no-reply@example.com"):
    # Synchronous wrapper for Celery tasks that are sync
    return asyncio.get_event_loop().run_until_complete(
        send_email_async(subject, html_body, to_email, from_email)
    )