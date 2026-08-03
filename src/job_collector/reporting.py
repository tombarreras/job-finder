"""Report generation for jobs."""
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from job_collector.models import JobStatus, NormalizedJob

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates JSON and Markdown reports."""

    def __init__(self, output_dir: Path | str) -> None:
        """Initialize report generator."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_reports(
        self,
        jobs: list[NormalizedJob],
        run_stats: dict[str, Any],
        source_errors: list[dict[str, str]],
        include_unchanged: bool = False,
    ) -> tuple[Path, Path]:
        """Generate both JSON and Markdown reports."""
        timestamp = datetime.utcnow()
        date_str = timestamp.strftime("%Y-%m-%d")

        # Generate JSON
        json_path = self._generate_json(jobs, run_stats, source_errors, date_str)

        # Generate Markdown
        md_path = self._generate_markdown(jobs, run_stats, source_errors, include_unchanged)

        # Also save to archive
        archive_dir = self.output_dir / "archive"
        archive_dir.mkdir(exist_ok=True)

        json_archive = archive_dir / f"{date_str}.json"
        md_archive = archive_dir / f"{date_str}.md"

        # _generate_* already return paths under output_dir; joining again would
        # look for output/output/. Copy rather than move so the latest_* files
        # the deployment docs point at stay in place.
        shutil.copy2(json_path, json_archive)
        shutil.copy2(md_path, md_archive)

        logger.info(f"Reports generated: {json_path}, {md_path}")
        return json_path, md_path

    def _generate_json(
        self,
        jobs: list[NormalizedJob],
        run_stats: dict[str, Any],
        source_errors: list[dict[str, str]],
        date_str: str,
    ) -> Path:
        """Generate JSON report."""
        timestamp = datetime.utcnow()

        # Categorize jobs by status
        jobs_by_status = {}
        for status in ["new", "changed", "expired", "unchanged"]:
            jobs_by_status[status] = [j for j in jobs if j.status.value == status]

        report = {
            "run": {
                "generated_at": timestamp.isoformat() + "Z",
                "status": "success",
                "source_count": run_stats.get("source_count", 0),
                "successful_sources": run_stats.get("successful_sources", 0),
                "failed_sources": run_stats.get("failed_sources", 0),
            },
            "jobs": {
                "new": self._serialize_jobs(jobs_by_status.get("new", [])),
                "changed": self._serialize_jobs(jobs_by_status.get("changed", [])),
                "expired": self._serialize_jobs(jobs_by_status.get("expired", [])),
            },
            "source_errors": source_errors,
        }

        output_path = self.output_dir / "latest_jobs.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

        return output_path

    def _generate_markdown(
        self,
        jobs: list[NormalizedJob],
        run_stats: dict[str, Any],
        source_errors: list[dict[str, str]],
        include_unchanged: bool = False,
    ) -> Path:
        """Generate Markdown report."""
        timestamp = datetime.utcnow()
        lines = []

        lines.append("# Job Collection Report")
        lines.append(f"\n**Generated:** {timestamp.isoformat()}Z")
        lines.append(f"**Sources checked:** {run_stats.get('source_count', 0)}")
        lines.append(
            f"**Status:** {run_stats.get('successful_sources', 0)} successful, "
            f"{run_stats.get('failed_sources', 0)} failed"
        )

        # Categorize by status and category. Every new job lands in exactly one
        # bucket, so nothing is silently dropped from the report.
        software_qa_categories = {"Software development", "QA and testing"}
        trades_categories = {
            "Electrical trade",
            "HVAC trade",
            "Construction and general labor",
        }
        austin_markers = ("Austin", "Round Rock", "Georgetown", "Texas", "TX")

        new_software_qa: list[NormalizedJob] = []
        new_trades: list[NormalizedJob] = []
        new_austin: list[NormalizedJob] = []
        new_other: list[NormalizedJob] = []

        for job in (j for j in jobs if j.status == JobStatus.NEW):
            if job.category in software_qa_categories:
                new_software_qa.append(job)
            elif job.category in trades_categories:
                new_trades.append(job)
            elif any(marker in job.location for marker in austin_markers):
                new_austin.append(job)
            else:
                new_other.append(job)

        changed = [j for j in jobs if j.status == JobStatus.CHANGED]
        expired = [j for j in jobs if j.status == JobStatus.EXPIRED]

        # New software and QA jobs
        if new_software_qa:
            lines.append(f"\n## New Software & QA Jobs ({len(new_software_qa)})")
            for job in new_software_qa:
                lines.extend(self._format_job_md(job))

        # New Austin-area technical jobs
        if new_austin:
            lines.append(f"\n## New Austin-Area Technical Jobs ({len(new_austin)})")
            for job in new_austin:
                lines.extend(self._format_job_md(job))

        # New trades/immediate income
        if new_trades:
            lines.append(f"\n## New Trades & Immediate Income Jobs ({len(new_trades)})")
            for job in new_trades:
                lines.extend(self._format_job_md(job))

        # Everything else that is new. Listed compactly rather than omitted, so
        # the report never understates what was collected.
        if new_other:
            lines.append(f"\n## Other New Jobs ({len(new_other)})")
            for job in new_other:
                lines.append(
                    f"- [{job.title}]({job.apply_url}) — {job.company_name}, {job.location}"
                )

        # Changed jobs
        if changed:
            lines.append(f"\n## Changed Jobs ({len(changed)})")
            for job in changed:
                lines.extend(self._format_job_md(job))

        # Expired jobs
        if expired:
            lines.append(f"\n## Expired Jobs ({len(expired)})")
            lines.append(f"{len(expired)} jobs are no longer posted")

        # Source errors
        if source_errors:
            lines.append(f"\n## Collection Problems ({len(source_errors)})")
            for error in source_errors:
                lines.append(f"- **{error['source']}**: {error['error']}")

        output_path = self.output_dir / "latest_report.md"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return output_path

    @staticmethod
    def _format_job_md(job: NormalizedJob) -> list[str]:
        """Format a single job for Markdown output."""
        lines = []
        lines.append(f"\n### {job.title}")
        lines.append(f"**{job.company_name}** | {job.location}")

        if job.employment_type:
            lines.append(f"*{job.employment_type.value}*")

        if job.remote_status:
            lines.append(f"*Remote: {job.remote_status.value}*")

        if job.salary_text:
            lines.append(f"**Salary:** {job.salary_text}")

        if job.warning_flags:
            lines.append(f"⚠️ **Warnings:** {', '.join(job.warning_flags)}")

        if job.description_text:
            # Truncate description
            description = job.description_text[:500]
            if len(job.description_text) > 500:
                description += "..."
            lines.append(f"\n{description}")

        lines.append(f"[Apply]({job.apply_url})")

        return lines

    @staticmethod
    def _serialize_jobs(jobs: list[NormalizedJob]) -> list[dict[str, Any]]:
        """Serialize jobs to JSON-compatible dicts."""
        result = []
        for job in jobs:
            result.append({
                "source": job.source_type,
                "source_id": job.source_job_id,
                "company": job.company_name,
                "title": job.title,
                "location": job.location,
                "employment_type": job.employment_type.value,
                "remote_status": job.remote_status.value,
                "salary": job.salary_text,
                "description": job.description_text[:2000],
                "apply_url": job.apply_url,
                "posted_date": job.date_posted.isoformat() if job.date_posted else None,
                "first_seen": job.first_seen_at.isoformat(),
                "warnings": job.warning_flags,
            })
        return result
