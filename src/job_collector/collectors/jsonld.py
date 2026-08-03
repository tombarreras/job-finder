"""JSON-LD job board collector."""
import asyncio
import json
import logging
import re
import uuid
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
from job_collector.normalization import calculate_content_hash

logger = logging.getLogger(__name__)


class JSONLDCollector(JobCollector):
    """Collects from pages with schema.org JobPosting JSON-LD."""

    async def collect(self) -> CollectionResult:
        """Collect jobs from JSON-LD page."""
        self._log_collection_start()
        start_time = datetime.utcnow()

        if not self.source_config.site_url:
            error = "Missing site_url for JSON-LD"
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
        """Fetch and parse JSON-LD jobs from page."""
        jobs = []

        response = await client.get(self.source_config.site_url)
        response.raise_for_status()

        # Extract JSON-LD blocks
        json_ld_blocks = self._extract_json_ld_blocks(response.text)

        for block in json_ld_blocks:
            try:
                # Handle @graph format
                if isinstance(block, dict) and "@graph" in block:
                    for item in block["@graph"]:
                        if item.get("@type") == "JobPosting" or "JobPosting" in item.get("@type", []):
                            try:
                                job = self._parse_job(item)
                                if job:
                                    jobs.append(job)
                            except Exception as e:
                                logger.warning(f"Failed to parse JobPosting: {e}")
                # Handle array of objects
                elif isinstance(block, list):
                    for item in block:
                        if item.get("@type") == "JobPosting" or "JobPosting" in item.get("@type", []):
                            try:
                                job = self._parse_job(item)
                                if job:
                                    jobs.append(job)
                            except Exception as e:
                                logger.warning(f"Failed to parse JobPosting: {e}")
                # Handle single object
                elif isinstance(block, dict):
                    if block.get("@type") == "JobPosting" or "JobPosting" in block.get("@type", []):
                        try:
                            job = self._parse_job(block)
                            if job:
                                jobs.append(job)
                        except Exception as e:
                            logger.warning(f"Failed to parse JobPosting: {e}")
            except Exception as e:
                logger.warning(f"Failed to process JSON-LD block: {e}")

        return jobs

    @staticmethod
    def _extract_json_ld_blocks(html: str) -> list[Any]:
        """Extract JSON-LD blocks from HTML."""
        blocks = []
        # Find all script tags with type=application/ld+json
        pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
        matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)

        for match in matches:
            try:
                data = json.loads(match)
                blocks.append(data)
            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON-LD block")

        return blocks

    @staticmethod
    def _format_address(addr: Any) -> str:
        """Format a schema.org PostalAddress as 'City, Region[, Country]'."""
        if not addr:
            return ""
        if not isinstance(addr, dict):
            return str(addr)

        parts = []
        if addr.get("addressLocality"):
            parts.append(addr["addressLocality"])
        if addr.get("addressRegion"):
            parts.append(addr["addressRegion"])
        # Domestic postings are the norm; "Austin, TX, USA" is noise.
        country = addr.get("addressCountry") or ""
        if isinstance(country, dict):
            country = country.get("name") or ""
        if country and str(country).upper() not in {"US", "USA", "UNITED STATES"}:
            parts.append(str(country))

        return ", ".join(parts)

    def _parse_job(self, job_data: dict[str, Any]) -> NormalizedJob | None:
        """Parse a JobPosting schema."""
        title = job_data.get("title", "")
        if not title:
            return None

        # Company name
        company_data = job_data.get("hiringOrganization", {})
        if isinstance(company_data, dict):
            company_name = company_data.get("name", self.company_id)
        else:
            company_name = str(company_data) if company_data else self.company_id

        # Job ID - use URL if available, otherwise generate
        job_url = job_data.get("url", "")
        job_id = job_data.get("identifier", "")
        if not job_id:
            job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, job_url)) if job_url else str(uuid.uuid4())

        # Location
        location = "Remote"
        location_data = job_data.get("jobLocation")
        if isinstance(location_data, list) and location_data:
            # Multiple locations - use first
            location_data = location_data[0]
        if isinstance(location_data, dict):
            formatted = self._format_address(location_data.get("address"))
            if formatted:
                location = formatted

        # Description
        description = ""
        if job_data.get("description"):
            description = str(job_data["description"])
        elif job_data.get("jobDescription"):
            description = str(job_data["jobDescription"])

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
        if job_data.get("jobLocationType"):
            # schema.org uses TELECOMMUTE/ON_SITE; separators vary by publisher.
            loc_type = str(job_data["jobLocationType"]).lower().replace("_", " ").replace("-", " ")
            if "remote" in loc_type or "telecommute" in loc_type:
                remote_status = RemoteStatus.REMOTE
            elif "hybrid" in loc_type:
                remote_status = RemoteStatus.HYBRID
            elif "on site" in loc_type:
                remote_status = RemoteStatus.ON_SITE

        # Apply URL
        apply_url = job_data.get("applicantLocationRequirements", "")
        if not apply_url:
            apply_url = job_url

        # Salary
        salary_text = ""
        salary_min = None
        salary_max = None
        salary_currency = "USD"

        if job_data.get("baseSalary"):
            salary_data = job_data["baseSalary"]
            if isinstance(salary_data, dict):
                salary_min = salary_data.get("minValue")
                salary_max = salary_data.get("maxValue")
                salary_currency = salary_data.get("currency", "USD")

                if salary_min and salary_max:
                    salary_text = f"${salary_min:,} - ${salary_max:,} {salary_currency}"

        # Dates
        date_posted = None
        if job_data.get("datePosted"):
            try:
                posted_str = job_data["datePosted"]
                if "T" in posted_str:
                    date_posted = datetime.fromisoformat(posted_str.replace("Z", "+00:00"))
                else:
                    date_posted = datetime.fromisoformat(posted_str)
            except (ValueError, AttributeError):
                pass

        # Calculate hash
        content_hash = calculate_content_hash(company_name, title, location, description, apply_url)

        return NormalizedJob(
            source_type="jsonld",
            source_company_id=self.company_id,
            source_job_id=job_id,
            company_name=company_name,
            title=title,
            location=location,
            apply_url=apply_url,
            source_url=job_url,
            date_posted=date_posted,
            description_text=description,
            employment_type=employment_type,
            remote_status=remote_status,
            salary_text=salary_text,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            content_hash=content_hash,
            raw_payload=job_data if self.source_config.parsing_config.get("store_raw") else {},
        )
