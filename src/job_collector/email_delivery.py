"""Email delivery for job reports."""
import logging
import os
import re
import smtplib
from datetime import datetime
from typing import Any
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
        attach_json: bool = True,
    ) -> bool:
        """Send email with report.

        The body carries the job records; the JSON attachment is supplementary,
        since the downstream reader receives it as application/octet-stream and
        cannot open it.
        """
        if not all([self.smtp_host, self.smtp_username, self.smtp_password, self.from_address]):
            logger.error("Email configuration incomplete")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_address
            msg["To"] = to_address

            # Descriptions carry curly quotes and non-breaking spaces, so be
            # explicit about the charset rather than relying on the default.
            msg.attach(MIMEText(body, "plain", "utf-8"))

            # Attach JSON report if available
            if attach_json and json_report_path and json_report_path.exists():
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

    #: Records are consumed by an automated reader, so the body must be
    #: self-contained and parseable. Attachments are not usable: they arrive as
    #: application/octet-stream and the reader cannot open them.
    MAX_DESCRIPTION_CHARS = 2000

    #: Gmail clips message bodies around 102 KB, and a clipped body would hide
    #: records from the reader without any indication. Stay under it.
    MAX_BODY_BYTES = 90_000

    @staticmethod
    def split_into_batches(
        jobs: list,
        max_bytes: int | None = None,
        max_jobs: int = 400,
    ) -> list[list]:
        """Pack jobs into batches that each fit one email body."""
        budget = EmailDelivery.MAX_BODY_BYTES if max_bytes is None else max_bytes
        # Leave room for the header, which is small but not free.
        budget = max(budget - 2000, 1000)

        batches: list[list] = []
        current: list = []
        used = 0

        for job in jobs:
            size = len("\n".join(EmailDelivery._format_job_record(job)).encode("utf-8")) + 1
            if current and (used + size > budget or len(current) >= max_jobs):
                batches.append(current)
                current, used = [], 0
            current.append(job)
            used += size

        if current:
            batches.append(current)
        return batches

    def send_reports(self, to_address: str, messages: list[tuple]) -> int:
        """Send several messages over one SMTP session.

        Used for backfills. Re-logging in per message risks tripping the
        provider's rate limits.
        """
        if not all([self.smtp_host, self.smtp_username, self.smtp_password, self.from_address]):
            logger.error("Email configuration incomplete")
            return 0

        sent = 0
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                for subject, body in messages:
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = subject
                    msg["From"] = self.from_address
                    msg["To"] = to_address
                    msg.attach(MIMEText(body, "plain", "utf-8"))
                    server.send_message(msg)
                    sent += 1
                    logger.info(f"Sent {subject}")
        except Exception as e:
            logger.exception(f"Batch send stopped after {sent} message(s): {e}")

        return sent

    @staticmethod
    def format_report_email(
        new_count: int,
        changed_count: int,
        expired_count: int,
        failed_sources: int,
        markdown_content: str = "",
        timestamp: datetime | None = None,
        jobs: "list | None" = None,
        total_active: int = 0,
        max_jobs: int = 400,
        max_bytes: int | None = None,
        part: int = 1,
        total_parts: int = 1,
    ) -> str:
        """Format the email body as a header plus one record per job.

        Each record runs from a line reading ``JOB`` to a line reading
        ``END JOB``; scalar fields are ``key: value`` and ``description`` comes
        last so it may span lines.
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        jobs = jobs or []
        budget = EmailDelivery.MAX_BODY_BYTES if max_bytes is None else max_bytes

        # Fit as many whole records as the budget allows. A clipped body would
        # drop records silently, so cut here and say how many were left out.
        included, rendered, used = [], [], 0
        for job in jobs[:max_jobs]:
            record = EmailDelivery._format_job_record(job)
            size = len("\n".join(record).encode("utf-8")) + 1
            if included and used + size > budget:
                break
            included.append(job)
            rendered.append(record)
            used += size

        lines = [
            "=== JOB COLLECTOR REPORT ===",
            f"generated_at: {timestamp.isoformat()}Z",
            f"total_active: {total_active}",
            f"new: {new_count}",
            f"changed: {changed_count}",
            f"expired: {expired_count}",
            f"failed_sources: {failed_sources}",
            f"part: {part} of {total_parts}",
            f"records_included: {len(included)}",
        ]
        if len(jobs) > len(included):
            # Never truncate silently -- a short report would otherwise read as
            # a quiet day rather than a capped one.
            reason = "record cap" if len(included) >= max_jobs else "body size limit"
            lines.append(
                f"records_omitted: {len(jobs) - len(included)} ({reason}; "
                f"ordered new-first, so omitted records are the lowest priority)"
            )
        lines.append("")

        for record in rendered:
            lines.extend(record)

        lines.append("=== END REPORT ===")
        return "\n".join(lines)

    @staticmethod
    def _format_job_record(job: Any) -> list[str]:
        """Render one job as a delimited record."""
        def scalar(value: Any) -> str:
            # Keep every field on a single line so parsing stays trivial.
            return re.sub(r"\s+", " ", str(value)).strip() if value else ""

        description = (job.description_text or "").strip()
        if len(description) > EmailDelivery.MAX_DESCRIPTION_CHARS:
            description = description[: EmailDelivery.MAX_DESCRIPTION_CHARS] + " [truncated]"
        # A description containing the terminator would split the record.
        description = re.sub(r"(?mi)^\s*END JOB\s*$", "END_JOB", description)

        return [
            "JOB",
            f"id: {scalar(job.source_id)}|{scalar(job.source_job_id)}",
            f"company: {scalar(job.company_name)}",
            f"title: {scalar(job.title)}",
            f"location: {scalar(job.location)}",
            f"employment_type: {scalar(getattr(job.employment_type, 'value', ''))}",
            f"remote: {scalar(getattr(job.remote_status, 'value', ''))}",
            f"status: {scalar(getattr(job.status, 'value', ''))}",
            f"posted_date: {job.date_posted.date().isoformat() if job.date_posted else ''}",
            f"first_seen: {job.first_seen_at.date().isoformat() if job.first_seen_at else ''}",
            f"source: {scalar(job.source_id)}",
            f"salary: {scalar(job.salary_text)}",
            f"apply_url: {scalar(job.apply_url)}",
            "description:",
            description,
            "END JOB",
            "",
        ]
