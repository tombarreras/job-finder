"""Ashby job board collector."""
import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

from job_collector.config import SourceConfig
from job_collector.collectors.base import JobCollector
from job_collector.models import (
    CollectionResult,
    EmploymentType,
    JobStatus,
    NormalizedJob,
    RemoteStatus,
)
from job_collector.normalization import calculate_content_hash, clean_html

logger = logging.getLogger(__name__)


class AshbyCollector(JobCollector):
    """Collects from Ashby public job boards."""

    BASE_URL = "https://api.ashby.io/public"

    async def collect(self) -> CollectionResult:
        """Collect jobs from Ashby board."""
        self._log_collection_start()
        start_time = datetime.utcnow()

        if not self.source_config.board_name:
            error = "Missing board_name for Ashby"
            logger.error(error)
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                errors=[error],
                complete=False,
            )

        try:
            async with httpx.AsyncClient(timeout=self.source_config.timeout_seconds) as client:
                jobs = await self._fetch_jobs(client)

            duration = (datetime.utcnow() - start_time).total_seconds()
            self._log_collection_end(duration, len(jobs), http_status=200)

            return CollectionResult(
                jobs=jobs,
                timestamp=datetime.utcnow(),
                http_status=200,
                duration_seconds=duration,
                complete=True,
            )
        except asyncio.TimeoutError:
            error = "Request timeout"
            logger.error(error)
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                errors=[error],
                http_status=408,
                complete=False,
            )
        except httpx.HTTPError as e:
            error = f"HTTP error: {e}"
            logger.error(error)
            status = getattr(e.response, "status_code", 0) if hasattr(e, "response") else 0
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                errors=[error],
                http_status=status or 500,
                complete=False,
            )
        except Exception as e:
            error = f"Unexpected error: {e}"
            logger.exception(error)
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                errors=[error],
                complete=False,
            )

    async def _fetch_jobs(self, client: httpx.AsyncClient) -> list[NormalizedJob]:
        """Fetch all jobs from Ashby API."""
        jobs = []
        cursor = None

        while True:
            payload = {"organizationName": self.source_config.board_name}
            if cursor:
                payload["cursor"] = cursor

            response = await client.post(
                f"{self.BASE_URL}/openings",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("results"):
                break

            for job_data in data["results"]:
                try:
                    job = self._parse_job(job_data)
                    jobs.append(job)
                except Exception as e:
                    logger.warning(f"Failed to parse job {job_data.get('id')}: {e}")

            # Check for more pages
            cursor = data.get("nextCursor")
            if not cursor:
                break

        return jobs

    def _parse_job(self, job_data: dict[str, Any]) -> NormalizedJob:
        """Parse a single Ashby job."""
        job_id = job_data["id"]
        title = job_data.get("title", "")
        company_name = self.company_id

        # Extract location
        location = "Remote"
        if job_data.get("location"):
            location_data = job_data["location"]
            if isinstance(location_data, dict):
                parts = []
                if location_data.get("city"):
                    parts.append(location_data["city"])
                if location_data.get("state"):
                    parts.append(location_data["state"])
                if location_data.get("country"):
                    parts.append(location_data["country"])
                if parts:
                    location = ", ".join(parts)
            else:
                location = str(location_data)

        # Extract description
        description = ""
        if job_data.get("descriptionPlain"):
            description = clean_html(job_data["descriptionPlain"])
        elif job_data.get("description"):
            description = clean_html(job_data["description"])

        # Extract department and team
        department = job_data.get("department", {}).get("name", "") if job_data.get("department") else ""
        team = job_data.get("team", {}).get("name", "") if job_data.get("team") else ""

        # Employment type
        employment_type = EmploymentType.FULL_TIME
        if job_data.get("employmentType"):
            emp_type = job_data["employmentType"].lower()
            if "part" in emp_type:
                employment_type = EmploymentType.PART_TIME
            elif "contract" in emp_type:
                employment_type = EmploymentType.CONTRACT
            elif "temporary" in emp_type:
                employment_type = EmploymentType.TEMPORARY

        # Remote status
        remote_status = RemoteStatus.UNKNOWN
        if job_data.get("isRemote") is True:
            remote_status = RemoteStatus.REMOTE
        elif job_data.get("isHybrid") is True:
            remote_status = RemoteStatus.HYBRID
        elif job_data.get("isRemote") is False:
            remote_status = RemoteStatus.ON_SITE

        # Workplace type
        workplace_type = job_data.get("workplaceType", "")

        # Dates
        date_posted = None
        if job_data.get("createdAt"):
            try:
                date_posted = datetime.fromisoformat(
                    job_data["createdAt"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        # Apply URL
        apply_url = job_data.get("applyUrl", job_data.get("url", ""))

        # Salary info
        salary_text = ""
        salary_min = None
        salary_max = None
        salary_currency = "USD"
        salary_period = "year"

        if job_data.get("compensation"):
            comp = job_data["compensation"]
            if comp.get("min") and comp.get("max"):
                salary_min = comp["min"]
                salary_max = comp["max"]
                salary_currency = comp.get("currency", "USD")
                salary_period = comp.get("period", "year")
                salary_text = f"${salary_min:,} - ${salary_max:,} {salary_period}"

        # Calculate hash
        content_hash = calculate_content_hash(company_name, title, location, description, apply_url)

        return NormalizedJob(
            source_type="ashby",
            source_company_id=self.company_id,
            source_job_id=job_id,
            company_name=company_name,
            title=title,
            location=location,
            apply_url=apply_url,
            source_url=job_data.get("url", apply_url),
            date_posted=date_posted,
            description_text=description,
            employment_type=employment_type,
            remote_status=remote_status,
            salary_text=salary_text,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_period=salary_period,
            content_hash=content_hash,
            department=department,
            team=team,
            workplace_type=workplace_type,
            raw_payload=job_data if self.source_config.parsing_config.get("store_raw") else {},
        )
