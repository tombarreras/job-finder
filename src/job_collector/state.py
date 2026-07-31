"""Job state management and change detection."""
import json
import logging
from datetime import datetime, timedelta

from job_collector.database import JobDatabase
from job_collector.models import JobStatus, NormalizedJob

logger = logging.getLogger(__name__)


class StateManager:
    """Manages job state transitions and change detection."""

    def __init__(self, database: JobDatabase) -> None:
        """Initialize state manager."""
        self.database = database

    def detect_status(
        self,
        new_job: NormalizedJob,
        source_id: str,
    ) -> tuple[NormalizedJob, str]:
        """Detect job status (new, changed, unchanged, expired, reopened)."""
        import sqlite3

        with sqlite3.connect(self.database.db_path) as conn:
            cursor = conn.cursor()

            # Check if job exists in database
            cursor.execute(
                """
                SELECT current_content_hash, active, content_hash
                FROM jobs
                WHERE source_id = ? AND source_job_id = ?
                LIMIT 1
                """,
                (source_id, new_job.source_job_id),
            )

            result = cursor.fetchone()

            if result is None:
                # Brand new job
                new_job.status = JobStatus.NEW
                return new_job, "new"

            current_hash, is_active, _ = result

            if not is_active:
                # Job was previously expired but is now active again
                new_job.status = JobStatus.REOPENED
                logger.info(f"Job {new_job.source_job_id} reopened")
                return new_job, "reopened"

            if new_job.content_hash == current_hash:
                # Content hasn't changed
                new_job.status = JobStatus.UNCHANGED
                return new_job, "unchanged"

            # Content has changed
            new_job.status = JobStatus.CHANGED
            logger.info(f"Job {new_job.source_job_id} changed")
            return new_job, "changed"

    def detect_expired_jobs(
        self,
        source_id: str,
        active_job_ids: set[str],
    ) -> list[str]:
        """Detect jobs that are no longer posted."""
        import sqlite3

        expired = []

        with sqlite3.connect(self.database.db_path) as conn:
            cursor = conn.cursor()

            # Get all currently active jobs from this source
            cursor.execute(
                """
                SELECT source_job_id FROM jobs
                WHERE source_id = ? AND active = 1
                """,
                (source_id,),
            )

            previously_active = {row[0] for row in cursor.fetchall()}

            # Jobs that were active but aren't in current results are expired
            expired_ids = previously_active - active_job_ids

            if expired_ids:
                # Mark jobs as inactive
                placeholders = ",".join("?" * len(expired_ids))
                cursor.execute(
                    f"""
                    UPDATE jobs
                    SET active = 0, last_seen_at = CURRENT_TIMESTAMP
                    WHERE source_id = ? AND source_job_id IN ({placeholders})
                    """,
                    [source_id] + list(expired_ids),
                )
                conn.commit()

                logger.info(f"Marked {len(expired_ids)} jobs as expired from {source_id}")

            return list(expired_ids)

    def detect_valid_through_expiration(self, job: NormalizedJob) -> bool:
        """Check if job has passed its valid-through date."""
        if not hasattr(job, 'valid_through_date') or not job.valid_through_date:
            return False

        if isinstance(job.valid_through_date, str):
            try:
                valid_through = datetime.fromisoformat(
                    job.valid_through_date.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                return False
        else:
            valid_through = job.valid_through_date

        return datetime.utcnow() > valid_through

    def get_jobs_by_status(
        self,
        source_id: str | None = None,
    ) -> dict[str, list[NormalizedJob]]:
        """Get all jobs grouped by status."""
        import sqlite3

        jobs_by_status = {
            "new": [],
            "changed": [],
            "unchanged": [],
            "expired": [],
            "reopened": [],
        }

        with sqlite3.connect(self.database.db_path) as conn:
            cursor = conn.cursor()

            query = "SELECT data_json FROM jobs WHERE 1=1"
            params = []

            if source_id:
                query += " AND source_id = ?"
                params.append(source_id)

            cursor.execute(query, params)

            for (data_json,) in cursor.fetchall():
                # Reconstruct job from JSON
                # TODO: Implement job deserialization
                pass

        return jobs_by_status

    def calculate_run_statistics(
        self,
        jobs: list[NormalizedJob],
    ) -> dict[str, int]:
        """Calculate statistics for a collection run."""
        return {
            "new": len([j for j in jobs if j.status == JobStatus.NEW]),
            "changed": len([j for j in jobs if j.status == JobStatus.CHANGED]),
            "unchanged": len([j for j in jobs if j.status == JobStatus.UNCHANGED]),
            "expired": len([j for j in jobs if j.status == JobStatus.EXPIRED]),
            "reopened": len([j for j in jobs if j.status == JobStatus.REOPENED]),
            "total": len(jobs),
        }

    def record_observation(
        self,
        job: NormalizedJob,
        source_id: str,
    ) -> None:
        """Record a job observation for change tracking."""
        import sqlite3
        import uuid

        with sqlite3.connect(self.database.db_path) as conn:
            cursor = conn.cursor()

            internal_id = f"{source_id}#{job.source_job_id}"
            observation_id = str(uuid.uuid4())

            cursor.execute(
                """
                INSERT INTO job_observations
                (observation_id, job_id, collection_timestamp, content_hash, observed_status)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
                """,
                (observation_id, internal_id, job.content_hash, job.status.value),
            )

            conn.commit()
