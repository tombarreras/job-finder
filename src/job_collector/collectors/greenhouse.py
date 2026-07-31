"""Greenhouse job board collector."""
import asyncio
import html
import logging
import re
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


class GreenhouseCollector(JobCollector):
    """Collects from Greenhouse public job boards."""

    BASE_URL = "https://boards-api.greenhouse.io/v1"

    async def collect(self) -> CollectionResult:
        """Collect jobs from Greenhouse board."""
        self._log_collection_start()
        start_time = datetime.utcnow()

        if not self.source_config.board_token:
            error = "Missing board_token for Greenhouse"
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
        """Fetch all jobs from Greenhouse API."""
        jobs = []
        page = 0
        per_page = 50

        while True:
            url = (
                f"{self.BASE_URL}/boards/{self.source_config.board_token}/jobs"
                f"?content=true&page={page}&per_page={per_page}"
            )

            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

            if not data.get("jobs"):
                break

            for job_data in data["jobs"]:
                try:
                    job = self._parse_job(job_data)
                    jobs.append(job)
                except Exception as e:
                    logger.warning(f"Failed to parse job {job_data.get('id')}: {e}")

            # Check if there are more pages
            if len(data["jobs"]) < per_page:
                break

            page += 1

        return jobs

    def _parse_job(self, job_data: dict[str, Any]) -> NormalizedJob:
        """Parse a single Greenhouse job."""
        job_id = str(job_data["id"])
        title = job_data.get("title", "")
        company_name = job_data.get("company", {}).get("name", self.company_id)

        # Extract locations
        locations = []
        for office in job_data.get("offices", []):
            if office.get("name"):
                locations.append(office["name"])
        location = ", ".join(locations) if locations else "Remote"

        # Extract departments
        departments = []
        for dept in job_data.get("departments", []):
            if dept.get("name"):
                departments.append(dept["name"])
        department = ", ".join(departments) if departments else ""

        # Parse description
        description = ""
        if job_data.get("content"):
            description = clean_html(job_data["content"])

        # Dates
        date_posted = None
        if job_data.get("published_at"):
            try:
                date_posted = datetime.fromisoformat(
                    job_data["published_at"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        # Determine remote status
        remote_status = RemoteStatus.UNKNOWN
        if "remote" in title.lower() or "work from home" in description.lower():
            remote_status = RemoteStatus.REMOTE

        # Apply URL
        apply_url = job_data.get("absolute_url", "")

        # Calculate hash
        content_hash = calculate_content_hash(company_name, title, location, description, apply_url)

        return NormalizedJob(
            source_type="greenhouse",
            source_company_id=self.company_id,
            source_job_id=job_id,
            company_name=company_name,
            title=title,
            location=location,
            apply_url=apply_url,
            source_url=apply_url,
            date_posted=date_posted,
            description_text=description,
            employment_type=EmploymentType.FULL_TIME,
            remote_status=remote_status,
            content_hash=content_hash,
            department=department,
            raw_payload=job_data if self.source_config.parsing_config.get("store_raw") else {},
        )
