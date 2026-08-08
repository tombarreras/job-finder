"""Lever job board collector."""
import asyncio
import logging
from datetime import datetime, timezone
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


class LeverCollector(JobCollector):
    """Collects from Lever public job boards."""

    BASE_URL = "https://api.lever.co/v0"

    async def collect(self) -> CollectionResult:
        """Collect jobs from Lever board."""
        self._log_collection_start()
        start_time = datetime.utcnow()

        if not self.source_config.board_name:
            error = "Missing board_name for Lever"
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
        """Fetch all postings from the Lever public API.

        The endpoint returns a plain JSON array of every posting -- not a
        paginated object. The previous implementation called `.get("data")` on
        that list and raised AttributeError against every real board.
        """
        url = f"{self.BASE_URL}/postings/{self.source_config.board_name}?mode=json"

        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list):
            logger.warning(f"Unexpected Lever payload: {type(data).__name__}")
            return []

        jobs = []
        for job_data in data:
            try:
                jobs.append(self._parse_job(job_data))
            except Exception as e:
                logger.warning(f"Failed to parse job {job_data.get('id')}: {e}")

        return jobs

    def _parse_job(self, job_data: dict[str, Any]) -> NormalizedJob:
        """Parse a single Lever job posting."""
        job_id = job_data["id"]
        title = job_data.get("text", "")
        company_name = self.company_id

        # Lever nests location, department, team and commitment under
        # "categories", all as plain strings. There is no top-level "locations"
        # list or dict-shaped department, which is what this used to expect.
        categories = job_data.get("categories") or {}

        all_locations = categories.get("allLocations") or []
        location = categories.get("location") or (
            ", ".join(all_locations) if all_locations else ""
        ) or "Remote"

        description = job_data.get("descriptionPlain") or ""
        if not description and job_data.get("description"):
            description = clean_html(job_data["description"])
        # "additionalPlain" carries requirements and benefits.
        if job_data.get("additionalPlain"):
            description = f"{description}\n\n{job_data['additionalPlain']}".strip()

        department = categories.get("department") or ""
        team = categories.get("team") or ""

        # Employment type comes from "commitment" ("Full-time", "Part-time",
        # "Contract", "Internship"), not from workplaceType.
        employment_type = EmploymentType.UNKNOWN
        commitment = (categories.get("commitment") or "").lower().replace("-", " ")
        if "full time" in commitment:
            employment_type = EmploymentType.FULL_TIME
        elif "part time" in commitment:
            employment_type = EmploymentType.PART_TIME
        elif "contract" in commitment or "temporary" in commitment:
            employment_type = EmploymentType.CONTRACT
        elif "intern" in commitment or "apprentice" in commitment:
            employment_type = EmploymentType.APPRENTICESHIP

        # Remote status
        remote_status = RemoteStatus.UNKNOWN
        if job_data.get("workplaceType"):
            workplace = job_data["workplaceType"].lower()
            if "remote" in workplace:
                remote_status = RemoteStatus.REMOTE
            elif "hybrid" in workplace:
                remote_status = RemoteStatus.HYBRID
            elif "office" in workplace or "onsite" in workplace or "on-site" in workplace:
                remote_status = RemoteStatus.ON_SITE

        # Dates
        date_posted = None
        if job_data.get("createdAt"):
            try:
                # Epoch milliseconds UTC, and sometimes sent as a string.
                # Parsing in local time would yield a different date on a UTC
                # CI runner than locally.
                date_posted = datetime.fromtimestamp(
                    int(job_data["createdAt"]) / 1000, tz=timezone.utc
                ).replace(tzinfo=None)
            except (ValueError, TypeError, OSError):
                pass

        apply_url = job_data.get("applyUrl") or job_data.get("hostedUrl") or ""

        # Calculate hash
        content_hash = calculate_content_hash(company_name, title, location, description, apply_url)

        return NormalizedJob(
            source_type="lever",
            source_company_id=self.company_id,
            source_job_id=job_id,
            company_name=company_name,
            title=title,
            location=location,
            apply_url=apply_url,
            source_url=job_data.get("hostedUrl") or apply_url,
            date_posted=date_posted,
            description_text=description,
            employment_type=employment_type,
            remote_status=remote_status,
            content_hash=content_hash,
            department=department,
            team=team,
            workplace_type=job_data.get("workplaceType", ""),
            raw_payload=job_data if self.source_config.parsing_config.get("store_raw") else {},
        )
