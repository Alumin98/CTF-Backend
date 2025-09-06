import os, smtplib
from email.message import EmailMessage

def send_email(to_email: str, subject: str, html_body: str, text_body: str = "") -> None:
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM", "CTF Platform <no-reply@example.com>")
    msg["To"] = to_email
    msg["Subject"] = subject
    if text_body:
        msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pwd  = os.getenv("SMTP_PASSWORD")

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        if user and pwd:
            s.login(user, pwd)
        s.send_message(msg)