"""Workday (CXS) job board collector.

Workday-hosted career sites are JavaScript applications, so the rendered HTML
contains no postings. They are all backed by the same public JSON endpoint::

    POST https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

which returns paginated summaries, plus a per-job detail endpoint::

    GET  https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}

The endpoint shape is identical across tenants, so one collector serves every
Workday employer.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from job_collector.config import SourceConfig
from job_collector.collectors.base import JobCollector
from job_collector.models import (
    CollectionResult,
    EmploymentType,
    NormalizedJob,
    RemoteStatus,
)
from job_collector.normalization import calculate_content_hash, clean_html

logger = logging.getLogger(__name__)

# Workday rejects page sizes above 20 on the public CXS endpoint.
PAGE_SIZE = 20

TENANT_URL_RE = re.compile(
    r"https?://(?P<tenant>[a-z0-9\-]+)\.(?P<wd_host>wd\d+)\.myworkdayjobs\.com/"
    r"(?:[a-z]{2}-[A-Z]{2}/)?(?P<site>[A-Za-z0-9_\-]+)",
    re.IGNORECASE,
)

# externalPath ends with the requisition id, e.g. "..._JR104602", "..._R-10065705".
REQ_ID_IN_PATH_RE = re.compile(r"_([A-Za-z]{1,5}-?\d[\w-]*)$")


class WorkdayCollector(JobCollector):
    """Collects from Workday-hosted career sites via the public CXS API."""

    #: Workday returns 403 for the default httpx user-agent on some tenants.
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    def __init__(self, company_id: str, source_config: SourceConfig) -> None:
        """Initialize collector, deriving tenant coordinates if needed."""
        super().__init__(company_id, source_config)
        self.tenant, self.wd_host, self.site = self._resolve_coordinates(source_config)

    @staticmethod
    def _resolve_coordinates(
        source_config: SourceConfig,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Resolve tenant/host/site from explicit fields or a careers URL."""
        tenant = source_config.tenant
        wd_host = source_config.wd_host
        site = source_config.site

        # Fall back to parsing the public careers URL, which is what
        # auto-discovery records.
        if not (tenant and site) and source_config.site_url:
            match = TENANT_URL_RE.match(source_config.site_url)
            if match:
                tenant = tenant or match.group("tenant")
                wd_host = wd_host or match.group("wd_host")
                site = site or match.group("site")

        return tenant, wd_host or "wd1", site

    @property
    def base_url(self) -> str:
        """Root of the tenant's Workday site."""
        return f"https://{self.tenant}.{self.wd_host}.myworkdayjobs.com"

    @property
    def api_url(self) -> str:
        """CXS API root for this tenant/site."""
        return f"{self.base_url}/wday/cxs/{self.tenant}/{self.site}"

    async def collect(self) -> CollectionResult:
        """Collect jobs from a Workday site."""
        self._log_collection_start()
        start_time = datetime.utcnow()

        if not self.tenant or not self.site:
            error = (
                "Missing Workday coordinates: provide tenant + site, or a "
                "site_url like https://acme.wd1.myworkdayjobs.com/Careers"
            )
            logger.error(error)
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                errors=[error],
                complete=False,
            )

        warnings: list[str] = []

        try:
            async with httpx.AsyncClient(
                timeout=self.source_config.timeout_seconds,
                headers=self.HEADERS,
            ) as client:
                jobs = await self._fetch_jobs(client, warnings)

            duration = (datetime.utcnow() - start_time).total_seconds()
            self._log_collection_end(duration, len(jobs), http_status=200)

            return CollectionResult(
                jobs=jobs,
                timestamp=datetime.utcnow(),
                warnings=warnings,
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
        except httpx.HTTPStatusError as e:
            # 404/422 almost always means the site id is wrong rather than the
            # tenant being gone -- surface that distinction to the operator.
            status = e.response.status_code
            hint = ""
            if status in (404, 422):
                hint = (
                    f" -- '{self.site}' is likely the wrong site id for tenant "
                    f"'{self.tenant}'; check the path in the public careers URL"
                )
            error = f"HTTP error: {e}{hint}"
            logger.error(error)
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                errors=[error],
                http_status=status,
                complete=False,
            )
        except httpx.HTTPError as e:
            error = f"HTTP error: {e}"
            logger.error(error)
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                errors=[error],
                http_status=500,
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

    async def _fetch_jobs(
        self,
        client: httpx.AsyncClient,
        warnings: list[str],
    ) -> list[NormalizedJob]:
        """Fetch, de-duplicate and parse all postings for this source."""
        parsing = self.source_config.parsing_config

        # Large tenants (Thermo Fisher carries 3000+ reqs) are best narrowed
        # server-side. Each term is a separate query; results are merged.
        search_terms = parsing.get("search_terms") or [""]
        max_jobs = int(parsing.get("max_jobs", 1000))

        summaries: dict[str, dict[str, Any]] = {}
        for term in search_terms:
            for summary in await self._search(client, term, max_jobs, warnings):
                path = summary.get("externalPath")
                if path and path not in summaries:
                    summaries[path] = summary

        if not summaries:
            return []

        details = await self._fetch_details(client, list(summaries), warnings)

        jobs = []
        for path, summary in summaries.items():
            try:
                jobs.append(self._parse_job(summary, details.get(path)))
            except Exception as e:
                logger.warning(f"Failed to parse job {path}: {e}")

        return jobs

    async def _search(
        self,
        client: httpx.AsyncClient,
        search_text: str,
        max_jobs: int,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        """Page through the CXS search endpoint for one search term."""
        found: list[dict[str, Any]] = []
        offset = 0
        total = None

        while offset < max_jobs:
            payload = {
                "appliedFacets": self.source_config.parsing_config.get("applied_facets", {}),
                "limit": PAGE_SIZE,
                "offset": offset,
                "searchText": search_text,
            }
            response = await client.post(f"{self.api_url}/jobs", json=payload)
            response.raise_for_status()
            data = response.json()

            if total is None:
                total = data.get("total", 0)

            postings = data.get("jobPostings") or []
            if not postings:
                break

            found.extend(postings)
            offset += PAGE_SIZE

            if total is not None and offset >= total:
                break

        if total and len(found) < total:
            message = (
                f"{self.company_id}: collected {len(found)} of {total} postings "
                f"for search '{search_text}' (max_jobs={max_jobs})"
            )
            logger.warning(message)
            warnings.append(message)

        return found

    async def _fetch_details(
        self,
        client: httpx.AsyncClient,
        paths: list[str],
        warnings: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Fetch per-job detail records, which carry the description and dates."""
        parsing = self.source_config.parsing_config
        if not parsing.get("fetch_descriptions", True):
            return {}

        # One request per posting, so cap it. Without a cap a single large
        # tenant would issue thousands of requests per daily run.
        #
        # Sort before truncating: the description feeds the content hash, so if
        # the capped subset shifted with the API's result ordering, unchanged
        # postings would flip hashes between runs and report as "changed".
        max_details = int(parsing.get("max_detail_fetches", 300))
        targets = sorted(paths)[:max_details]
        if len(paths) > max_details:
            message = (
                f"{self.company_id}: fetched descriptions for {max_details} of "
                f"{len(paths)} postings (max_detail_fetches={max_details})"
            )
            logger.warning(message)
            warnings.append(message)

        semaphore = asyncio.Semaphore(int(parsing.get("detail_concurrency", 5)))
        details: dict[str, dict[str, Any]] = {}

        async def fetch(path: str) -> None:
            async with semaphore:
                try:
                    response = await client.get(f"{self.api_url}{path}")
                    response.raise_for_status()
                    info = response.json().get("jobPostingInfo")
                    if info:
                        details[path] = info
                except Exception as e:
                    # A missing description should not sink the whole source.
                    logger.warning(f"Failed to fetch detail for {path}: {e}")

        await asyncio.gather(*(fetch(p) for p in targets))
        return details

    def _parse_job(
        self,
        summary: dict[str, Any],
        detail: Optional[dict[str, Any]] = None,
    ) -> NormalizedJob:
        """Parse a Workday posting into the normalized model."""
        detail = detail or {}
        external_path = summary.get("externalPath", "")
        title = detail.get("title") or summary.get("title", "")

        # Prefer the requisition id, which survives edits to the title. Do not
        # trust bulletFields[0]: some tenants put a label like "Spotlight Job"
        # there, which would collapse every such posting onto one id.
        job_id = detail.get("jobReqId") or ""
        if not job_id and external_path:
            match = REQ_ID_IN_PATH_RE.search(external_path)
            job_id = match.group(1) if match else external_path

        location = detail.get("location") or summary.get("locationsText") or "Unknown"

        description = ""
        if detail.get("jobDescription"):
            description = clean_html(detail["jobDescription"])

        apply_url = detail.get("externalUrl") or (
            f"{self.base_url}/{self.site}{external_path}" if external_path else ""
        )

        time_type = detail.get("timeType") or summary.get("timeType") or ""
        employment_type = self._parse_employment_type(time_type, title)
        remote_status = self._parse_remote_status(location, title)

        date_posted = self._parse_start_date(detail.get("startDate"))
        if date_posted is None:
            date_posted = self._parse_posted_on(
                detail.get("postedOn") or summary.get("postedOn", "")
            )

        content_hash = calculate_content_hash(
            self.company_id, title, location, description, apply_url
        )

        return NormalizedJob(
            source_type="workday",
            source_company_id=self.company_id,
            source_job_id=str(job_id),
            company_name=self.company_id,
            title=title,
            location=location,
            apply_url=apply_url,
            source_url=apply_url,
            date_posted=date_posted,
            description_text=description,
            employment_type=employment_type,
            remote_status=remote_status,
            content_hash=content_hash,
            raw_payload=(
                {"summary": summary, "detail": detail}
                if self.source_config.parsing_config.get("store_raw")
                else {}
            ),
        )

    @staticmethod
    def _parse_employment_type(time_type: str, title: str) -> EmploymentType:
        """Map Workday's timeType, letting an apprenticeship title win."""
        haystack = title.lower()
        if "apprentice" in haystack:
            return EmploymentType.APPRENTICESHIP

        normalized = time_type.lower().replace("-", " ")
        if "part time" in normalized:
            return EmploymentType.PART_TIME
        if "full time" in normalized:
            return EmploymentType.FULL_TIME
        if "contract" in normalized:
            return EmploymentType.CONTRACT
        if "temporary" in normalized or "seasonal" in normalized:
            return EmploymentType.TEMPORARY
        return EmploymentType.UNKNOWN

    @staticmethod
    def _parse_remote_status(location: str, title: str) -> RemoteStatus:
        """Infer remote status from the location and title text."""
        haystack = f"{location} {title}".lower()
        if "hybrid" in haystack:
            return RemoteStatus.HYBRID
        if "remote" in haystack or "work from home" in haystack:
            return RemoteStatus.REMOTE
        return RemoteStatus.UNKNOWN

    @staticmethod
    def _parse_start_date(value: Optional[str]) -> Optional[datetime]:
        """Parse the detail endpoint's absolute ISO start date."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _parse_posted_on(
        text: str,
        now: Optional[datetime] = None,
    ) -> Optional[datetime]:
        """Parse Workday's relative postedOn text, e.g. 'Posted 5 Days Ago'.

        Only the summary endpoint is relative; the detail endpoint gives an
        absolute startDate, which is preferred when available.
        """
        if not text:
            return None

        now = now or datetime.utcnow()
        normalized = text.lower()

        if "today" in normalized or "just posted" in normalized:
            return now
        if "yesterday" in normalized:
            return now - timedelta(days=1)

        match = re.search(r"(\d+)\+?\s*day", normalized)
        if match:
            return now - timedelta(days=int(match.group(1)))

        match = re.search(r"(\d+)\+?\s*month", normalized)
        if match:
            return now - timedelta(days=30 * int(match.group(1)))

        return None
