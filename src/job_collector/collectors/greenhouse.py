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
        """Fetch all jobs from the Greenhouse boards API.

        The endpoint returns the whole board in one response and ignores
        `page`/`per_page`. Requesting successive pages returned an identical
        full list every time, so the previous loop -- which stopped only once a
        page came back short -- never terminated.
        """
        url = f"{self.BASE_URL}/boards/{self.source_config.board_token}/jobs?content=true"

        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

        jobs = []
        for job_data in data.get("jobs") or []:
            try:
                jobs.append(self._parse_job(job_data))
            except Exception as e:
                logger.warning(f"Failed to parse job {job_data.get('id')}: {e}")

        return jobs

    def _parse_job(self, job_data: dict[str, Any]) -> NormalizedJob:
        """Parse a single Greenhouse job."""
        job_id = str(job_data["id"])
        title = job_data.get("title", "")
        company_name = job_data.get("company", {}).get("name", self.company_id)

        # The posting's own location is authoritative. `offices[].name` is the
        # office's *name* ("Tecovas HQ", "AlertMedia HQ"), not a place, so
        # relying on it made those employers look out-of-area and dropped them.
        location = (job_data.get("location") or {}).get("name") or ""

        if not location:
            # Fall back to the offices, preferring their address over their name.
            parts = [
                office.get("location") or office.get("name")
                for office in job_data.get("offices") or []
                if office.get("location") or office.get("name")
            ]
            location = ", ".join(parts)

        location = location or "Remote"

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

        # Dates. The boards API sends "first_published"; "published_at" is
        # always null there, so reading only that left every job undated.
        date_posted = None
        for field in ("first_published", "published_at", "updated_at"):
            value = job_data.get(field)
            if not value:
                continue
            try:
                date_posted = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                break
            except (ValueError, AttributeError):
                continue

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
