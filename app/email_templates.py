import os

def reset_link(token: str) -> str:
    frontend = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    return f"{frontend}/reset-password?token={token}"

def reset_email_html(link: str) -> str:
    return f"""
      <p>We received a request to reset your password.</p>
      <p><a href="{link}">Click here to reset your password</a></p>
      <p>This link will expire in 60 minutes. If you didn’t request this, you can safely ignore this email.</p>
    """