import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import aiosmtplib
from app.core.config import settings
from loguru import logger
import traceback
import ssl
import asyncio

async def send_email(to_email: str, subject: str, html_content: str, text_content: str = None):
    """Send email using synchronous smtplib in a background thread."""
    
    # Create a function that runs synchronously
    def _send_email_sync():
        try:
            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = settings.EMAIL_SENDER
            message["To"] = to_email
            
            # Add text and HTML parts
            if text_content:
                message.attach(MIMEText(text_content, "plain"))
            message.attach(MIMEText(html_content, "html"))
            
            # Log attempt
            logger.info(f"Sending email to {to_email} with subject: {subject}")
            
            # Connect to SMTP server based on port
            if settings.SMTP_PORT == 465:
                # Use SSL
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, 
                                     context=context, timeout=30) as server:
                    if settings.SMTP_USER and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.send_message(message)
            else:
                # Use regular SMTP with optional STARTTLS
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
                    server.ehlo()  # Identify to the SMTP server
                    if settings.SMTP_TLS:
                        server.starttls(context=ssl.create_default_context())
                        server.ehlo()  # Re-identify over TLS connection
                    if settings.SMTP_USER and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.send_message(message)
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    # Run the synchronous function in a thread pool
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _send_email_sync)
        return result
    except Exception as e:
        logger.error(f"Error in send_email executor: {str(e)}")
        if settings.DEBUG:
            # In debug mode, log but don't fail
            logger.warning("DEBUG mode: Email sending failed but continuing")
            return True
        # In production, propagate the error
        raise
async def send_verification_email(email: str, name: str, verification_url: str):
    """Send email verification link."""
    subject = "Bluescan: Verify your email address"
    
    html_content = f"""
    <html>
    <body>
        <h2>Email Verification</h2>
        <p>Hello {name},</p>
        <p>Thank you for registering with Bluescan. Please verify your email address by clicking the link below:</p>
        <p><a href="{verification_url}">Verify Email Address</a></p>
        <p>If you didn't register for an account, you can safely ignore this email.</p>
        <p>Best regards,<br>The Bluescan Team</p>
    </body>
    </html>
    """
    
    text_content = f"""
    Email Verification
    
    Hello {name},
    
    Thank you for registering with Bluescan. Please verify your email address by clicking the link below:
    
    {verification_url}
    
    If you didn't register for an account, you can safely ignore this email.
    
    Best regards,
    The Bluescan Team
    """
    
    return await send_email(email, subject, html_content, text_content)

async def send_password_reset_email(email: str, name: str, reset_url: str):
    """Send password reset link."""
    subject = "Reset your password"
    
    html_content = f"""
    <html>
    <body>
        <h2>Password Reset</h2>
        <p>Hello {name},</p>
        <p>We received a request to reset your password. Click the link below to create a new password:</p>
        <p><a href="{reset_url}">Reset Password</a></p>
        <p>If you didn't request a password reset, you can safely ignore this email.</p>
        <p>Best regards,<br>The Bluescan Team</p>
    </body>
    </html>
    """
    
    text_content = f"""
    Password Reset
    
    Hello {name},
    
    We received a request to reset your password. Click the link below to create a new password:
    
    {reset_url}
    
    If you didn't request a password reset, you can safely ignore this email.
    
    Best regards,
    The Bluescan Team
    """
    
    return await send_email(email, subject, html_content, text_content)