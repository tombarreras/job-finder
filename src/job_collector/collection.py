"""Job collection orchestration."""
import asyncio
import logging
from datetime import datetime
from typing import Any

from job_collector.collectors.ashby import AshbyCollector
from job_collector.collectors.base import JobCollector
from job_collector.collectors.greenhouse import GreenhouseCollector
from job_collector.collectors.jsonld import JSONLDCollector
from job_collector.collectors.lever import LeverCollector
from job_collector.collectors.workday import WorkdayCollector
from job_collector.config import JobCollectorConfig, SourceConfig
from job_collector.database import JobDatabase
from job_collector.models import JobStatus, NormalizedJob
from job_collector.normalization import calculate_content_hash

logger = logging.getLogger(__name__)


class JobCollectionOrchestrator:
    """Orchestrates job collection from multiple sources."""

    COLLECTOR_MAP = {
        "greenhouse": GreenhouseCollector,
        "lever": LeverCollector,
        "ashby": AshbyCollector,
        "jsonld": JSONLDCollector,
        "workday": WorkdayCollector,
    }

    def __init__(self, config: JobCollectorConfig, database: JobDatabase) -> None:
        """Initialize orchestrator."""
        self.config = config
        self.database = database
        self.results: list[dict[str, Any]] = []

    async def collect_all(
        self,
        source_filter: str | None = None,
        company_filter: str | None = None,
    ) -> dict[str, Any]:
        """Collect jobs from all enabled sources."""
        start_time = datetime.utcnow()
        all_jobs = []
        source_errors = []

        # Collect from all enabled companies
        tasks = []
        for company in self.config.companies:
            if not company.enabled:
                continue
            if company_filter and company.id != company_filter:
                continue

            for source in company.sources:
                if not source.enabled:
                    continue
                if source_filter and source.type != source_filter:
                    continue

                # Create collector
                collector_class = self.COLLECTOR_MAP.get(source.type)
                if not collector_class:
                    logger.warning(f"Unknown collector type: {source.type}")
                    continue

                collector = collector_class(company.id, source)
                tasks.append(self._collect_from_source(collector, company.id, source))

        # Run all collectors concurrently
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Collection task failed: {result}")
                    continue

                jobs, company_id, source, errors = result

                # Collect only; persisting here would make every job look like
                # it already existed once status detection queries the table.
                all_jobs.extend(jobs)

                # Track errors
                if errors:
                    source_errors.append({
                        "source": f"{company_id} ({source.type})",
                        "error": "; ".join(errors),
                    })

                # Update source status
                source_id = f"{company_id}#{source.type}"
                if errors:
                    self.database.update_source_status(
                        source_id,
                        "error",
                        "; ".join(errors),
                    )
                else:
                    self.database.update_source_status(source_id, "success")

        # Detect job status changes against the previous run's state, then
        # persist. Expired entries are placeholders, not real postings.
        all_jobs = self._detect_status_changes(all_jobs)

        for job in all_jobs:
            if job.status == JobStatus.EXPIRED:
                continue
            self.database.save_job(job, f"{job.source_company_id}#{job.source_type}")

        # Count jobs by status
        stats = {
            "source_count": len([
                s for c in self.config.companies
                for s in c.sources
                if c.enabled and s.enabled
            ]),
            "successful_sources": len([r for r in self.results if not r.get("error")]),
            "failed_sources": len([r for r in self.results if r.get("error")]),
            "new_count": len([j for j in all_jobs if j.status == JobStatus.NEW]),
            "changed_count": len([j for j in all_jobs if j.status == JobStatus.CHANGED]),
            "expired_count": len([j for j in all_jobs if j.status == JobStatus.EXPIRED]),
        }

        end_time = datetime.utcnow()

        return {
            "jobs": all_jobs,
            "source_errors": source_errors,
            "stats": stats,
            "duration": (end_time - start_time).total_seconds(),
            "timestamp": end_time,
        }

    async def _collect_from_source(
        self,
        collector: JobCollector,
        company_id: str,
        source: SourceConfig,
    ) -> tuple[list[NormalizedJob], str, SourceConfig, list[str]]:
        """Collect from a single source."""
        try:
            result = await collector.collect()

            self.results.append({
                "company": company_id,
                "source": source.type,
                "status": "success" if not result.errors else "error",
                "job_count": len(result.jobs),
                "error": result.errors[0] if result.errors else None,
                "http_status": result.http_status,
                "duration": result.duration_seconds,
            })

            return result.jobs, company_id, source, result.errors
        except Exception as e:
            logger.exception(f"Collection from {company_id}/{source.type} failed: {e}")
            self.results.append({
                "company": company_id,
                "source": source.type,
                "status": "error",
                "error": str(e),
            })
            return [], company_id, source, [str(e)]

    def _detect_status_changes(self, new_jobs: list[NormalizedJob]) -> list[NormalizedJob]:
        """Detect job status changes from previous collection."""
        from job_collector.state import StateManager

        state_manager = StateManager(self.database)
        processed = []

        # Group jobs by source for expiration detection
        jobs_by_source: dict[str, list[NormalizedJob]] = {}
        source_job_ids: dict[str, set[str]] = {}

        for job in new_jobs:
            source_id = f"{job.source_company_id}#{job.source_type}"

            if source_id not in jobs_by_source:
                jobs_by_source[source_id] = []
                source_job_ids[source_id] = set()

            jobs_by_source[source_id].append(job)
            source_job_ids[source_id].add(job.source_job_id)

        # Detect status for each job
        for job in new_jobs:
            source_id = f"{job.source_company_id}#{job.source_type}"

            # Detect status changes
            job, status_reason = state_manager.detect_status(job, source_id)

            # Record observation
            state_manager.record_observation(job, source_id)

            processed.append(job)

        # Detect expired jobs
        for source_id, active_ids in source_job_ids.items():
            expired_ids = state_manager.detect_expired_jobs(source_id, active_ids)

            # Add expired jobs to results
            for expired_id in expired_ids:
                expired_job = NormalizedJob(
                    source_type=new_jobs[0].source_type if new_jobs else "unknown",
                    source_company_id=new_jobs[0].source_company_id if new_jobs else "unknown",
                    source_job_id=expired_id,
                    company_name="",
                    title="",
                    location="",
                    apply_url="",
                    source_url="",
                    status=JobStatus.EXPIRED,
                )
                processed.append(expired_job)

        return processed
