import random
import smtplib
from email.mime.text import MIMEText

from app.config import settings


def generate_otp_code() -> str:
    """6-digit numeric code, matching the otp.dart 6-box UI exactly."""
    return f"{random.randint(0, 999999):06d}"


def send_otp_email(to_email: str, code: str) -> None:
    """
    Sends the OTP via SMTP. Works with:
    - Gmail SMTP (free, use an "App Password", not your normal Gmail password)
    - Brevo SMTP (free tier, ~300 emails/day, more reliable for production)

    If SMTP isn't configured yet (e.g. local dev without a .env), this just
    prints the code to the console so you can keep testing without email setup.
    """
    if not settings.smtp_host:
        print(f"[DEV MODE] OTP for {to_email}: {code}")
        return

    message = MIMEText(f"Your Hostel Yaar verification code is: {code}\n\nExpires in {settings.otp_expire_minutes} minutes.")
    message["Subject"] = "Hostel Yaar - Password Reset Code"
    message["From"] = settings.smtp_from_email
    message["To"] = to_email

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        server.login(settings.smtp_username, settings.smtp_password)
        server.sendmail(settings.smtp_from_email, [to_email], message.as_string())
