import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _send_email_sync(receiver: str, subject: str, message_body: str) -> None:
    """Synchronous function to send email via smtplib."""
    settings = get_settings()
    
    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured. Mocking email send.")
        logger.info(f"--- MOCK EMAIL ---\nTo: {receiver}\nSubject: {subject}\nBody: {message_body}\n------------------")
        return

    try:
        mail_message = MIMEMultipart()
        mail_message['From'] = settings.SMTP_FROM_EMAIL or settings.SMTP_USERNAME
        mail_message['To'] = receiver
        mail_message['Subject'] = subject
        mail_message.attach(MIMEText(message_body, 'html'))

        logger.info(f"Sending email to {receiver}...")
        
        server = smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT)
        server.starttls()
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(mail_message)
        server.quit()
        
        logger.info(f"Email sent successfully to {receiver}")

    except Exception as ex:
        logger.error(f"Failed to send email to {receiver}: {ex}")
        raise


async def send_email(receiver: str, subject: str, html_body: str) -> None:
    """Async wrapper for sending emails."""
    await asyncio.to_thread(_send_email_sync, receiver, subject, html_body)


async def send_signup_otp_email(receiver: str, otp: str, username: str = "User") -> None:
    """Send the 6-digit OTP for signup verification."""
    subject = "Verify your email address - Ontology Chatbot"
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2>Verify your email address</h2>
        <p>Thank You {username} for signing up.</p>
        <p>Please use the following 6-digit verification code to complete your registration:</p>
        <div style="background-color: #f4f4f5; padding: 16px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 4px; border-radius: 8px; margin: 24px 0;">
            {otp}
        </div>
        <p>This code will expire in 10 minutes.</p>
        <p>If you did not request this code, please ignore this email.</p>
    </div>
    """
    await send_email(receiver, subject, html_body)


async def send_password_reset_otp_email(receiver: str, otp: str, username: str = "User") -> None:
    """Send the 6-digit OTP for password reset."""
    subject = "Reset your password - Ontology Chatbot"
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2>Password Reset Request</h2>
        <p>Hello {username}, We received a request to reset your password for your Ontology Chatbot account.</p>
        <p>Please use the following 6-digit verification code to reset your password:</p>
        <div style="background-color: #f4f4f5; padding: 16px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 4px; border-radius: 8px; margin: 24px 0;">
            {otp}
        </div>
        <p>This code will expire in 10 minutes.</p>
        <p>If you did not request a password reset, please ignore this email. Your password will remain unchanged.</p>
    </div>
    """
    await send_email(receiver, subject, html_body)
