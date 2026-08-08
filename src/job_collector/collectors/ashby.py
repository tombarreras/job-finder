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

    BASE_URL = "https://api.ashbyhq.com/posting-api"

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
        """Fetch the whole job board from Ashby's public posting API.

        A single GET returns every listed posting; there is no cursor. The
        previous implementation POSTed to api.ashby.io, a host that does not
        resolve, so it failed against every board.
        """
        url = f"{self.BASE_URL}/job-board/{self.source_config.board_name}"

        response = await client.get(url, params={"includeCompensation": "true"})
        response.raise_for_status()
        data = response.json() or {}

        jobs = []
        for job_data in data.get("jobs") or []:
            # Unlisted postings are drafts or internal-only.
            if job_data.get("isListed") is False:
                continue
            try:
                jobs.append(self._parse_job(job_data))
            except Exception as e:
                logger.warning(f"Failed to parse job {job_data.get('id')}: {e}")

        return jobs

    def _parse_job(self, job_data: dict[str, Any]) -> NormalizedJob:
        """Parse a single Ashby job."""
        job_id = job_data["id"]
        title = job_data.get("title", "")
        company_name = self.company_id

        # location is a plain string ("Austin, Texas"), not a city/state/country
        # dict. department and team are strings too.
        location = job_data.get("location") or ""
        secondary = [
            s.get("location") if isinstance(s, dict) else str(s)
            for s in job_data.get("secondaryLocations") or []
        ]
        secondary = [s for s in secondary if s]
        if secondary:
            location = ", ".join([location, *secondary]) if location else ", ".join(secondary)
        location = location or "Remote"

        description = job_data.get("descriptionPlain") or ""
        if not description and job_data.get("descriptionHtml"):
            description = clean_html(job_data["descriptionHtml"])

        department = job_data.get("department") or ""
        team = job_data.get("team") or ""

        # employmentType is CamelCase: FullTime, PartTime, Intern, Contract,
        # Temporary.
        employment_type = EmploymentType.UNKNOWN
        emp_type = (job_data.get("employmentType") or "").lower()
        if "fulltime" in emp_type or "full time" in emp_type:
            employment_type = EmploymentType.FULL_TIME
        elif "parttime" in emp_type or "part time" in emp_type:
            employment_type = EmploymentType.PART_TIME
        elif "contract" in emp_type:
            employment_type = EmploymentType.CONTRACT
        elif "temporary" in emp_type:
            employment_type = EmploymentType.TEMPORARY
        elif "intern" in emp_type or "apprentice" in emp_type:
            employment_type = EmploymentType.APPRENTICESHIP

        # workplaceType is CamelCase: Remote, Hybrid, OnSite.
        workplace_type = job_data.get("workplaceType") or ""
        workplace = workplace_type.lower()
        remote_status = RemoteStatus.UNKNOWN
        if "hybrid" in workplace:
            remote_status = RemoteStatus.HYBRID
        elif "remote" in workplace:
            remote_status = RemoteStatus.REMOTE
        elif "onsite" in workplace or "on site" in workplace:
            remote_status = RemoteStatus.ON_SITE
        elif job_data.get("isRemote") is True:
            remote_status = RemoteStatus.REMOTE

        # publishedAt is ISO 8601; there is no createdAt on this endpoint.
        date_posted = None
        for field in ("publishedAt", "createdAt", "updatedAt"):
            value = job_data.get(field)
            if not value:
                continue
            try:
                date_posted = datetime.fromisoformat(
                    str(value).replace("Z", "+00:00")
                ).replace(tzinfo=None)
                break
            except (ValueError, AttributeError):
                continue

        apply_url = job_data.get("applyUrl") or job_data.get("jobUrl") or ""

        # Salary info
        salary_text = ""
        salary_min = None
        salary_max = None
        salary_currency = "USD"
        salary_period = "year"

        comp = job_data.get("compensation") or {}
        # The posting API returns a pre-rendered summary when the employer
        # publishes pay; the structured tiers are frequently empty.
        summary = comp.get("compensationTierSummary") or comp.get(
            "scrapeableCompensationSalarySummary"
        )
        if summary:
            salary_text = str(summary)
        elif comp.get("min") and comp.get("max"):
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
            source_url=job_data.get("jobUrl") or apply_url,
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
