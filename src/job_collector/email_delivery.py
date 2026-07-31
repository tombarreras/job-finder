"""Email delivery for job reports."""
import logging
import os
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)


class EmailDelivery:
    """Handles email delivery of job reports."""

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int = 587,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        from_address: str | None = None,
    ) -> None:
        """Initialize email delivery."""
        self.smtp_host = smtp_host or os.getenv("JOB_EMAIL_SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username or os.getenv("JOB_EMAIL_SMTP_USERNAME")
        self.smtp_password = smtp_password or os.getenv("JOB_EMAIL_SMTP_PASSWORD")
        self.from_address = from_address or os.getenv("JOB_EMAIL_FROM")

    def send_report(
        self,
        to_address: str,
        subject: str,
        body: str,
        json_report_path: Path | None = None,
        markdown_report_path: Path | None = None,
    ) -> bool:
        """Send email with report."""
        if not all([self.smtp_host, self.smtp_username, self.smtp_password, self.from_address]):
            logger.error("Email configuration incomplete")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_address
            msg["To"] = to_address

            # Add body as plain text
            msg.attach(MIMEText(body, "plain"))

            # Attach JSON report if available
            if json_report_path and json_report_path.exists():
                with open(json_report_path, "rb") as attachment:
                    part = MIMEApplication(attachment.read(), Name=json_report_path.name)
                    part["Content-Disposition"] = f'attachment; filename="{json_report_path.name}"'
                    msg.attach(part)

            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)

            logger.info(f"Email sent to {to_address}")
            return True

        except Exception as e:
            logger.exception(f"Failed to send email: {e}")
            return False

    @staticmethod
    def format_report_email(
        new_count: int,
        changed_count: int,
        expired_count: int,
        failed_sources: int,
        markdown_content: str,
        timestamp: datetime | None = None,
    ) -> str:
        """Format email body."""
        if timestamp is None:
            timestamp = datetime.utcnow()

        body = f"""Job Collection Report - {timestamp.strftime('%Y-%m-%d %H:%M')} UTC

Summary:
- New jobs: {new_count}
- Changed jobs: {changed_count}
- Expired jobs: {expired_count}
- Failed sources: {failed_sources}

{markdown_content}

This is an automated report from the job collection system.
"""
        return body
