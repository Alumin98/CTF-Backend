import os, ssl, smtplib, logging
from email.message import EmailMessage

def send_email(to_email: str, subject: str, html: str, text: str | None = None) -> bool:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", user or "no-reply@example.com")

    if not (host and user and password):
        logging.warning("SMTP not configured; skipping actual send. Would send to %s", to_email)
        logging.info("Subject: %s\nBody (text): %s\nBody (html): %s", subject, text, html)
        return False

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    if html:
        msg.set_content(text or "Open in an HTML-capable client.")
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(text or "")

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port) as s:
        s.starttls(context=context)
        s.login(user, password)
        s.send_message(msg)

    return True