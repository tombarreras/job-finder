"""SQLite database management for persistent state."""
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from job_collector.models import EmploymentType, JobStatus, NormalizedJob, RemoteStatus

logger = logging.getLogger(__name__)


class JobDatabase:
    """SQLite database for job state persistence."""

    def __init__(self, db_path: Path | str) -> None:
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS companies (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT 1,
                    priority TEXT DEFAULT 'medium',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_key TEXT,
                    enabled BOOLEAN DEFAULT 1,
                    last_attempted_at TEXT,
                    last_successful_at TEXT,
                    last_status TEXT,
                    last_error TEXT,
                    consecutive_failures INTEGER DEFAULT 0,
                    FOREIGN KEY (company_id) REFERENCES companies(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    internal_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_job_id TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    location TEXT,
                    apply_url TEXT,
                    source_url TEXT NOT NULL,
                    current_content_hash TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_changed_at TEXT,
                    active BOOLEAN DEFAULT 1,
                    data_json TEXT,
                    FOREIGN KEY (source_id) REFERENCES sources(id),
                    UNIQUE(source_id, source_job_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_observations (
                    observation_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    collection_timestamp TEXT NOT NULL,
                    content_hash TEXT,
                    observed_status TEXT NOT NULL,
                    normalized_snapshot TEXT,
                    FOREIGN KEY (job_id) REFERENCES jobs(internal_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS report_runs (
                    run_id TEXT PRIMARY KEY,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    status TEXT NOT NULL,
                    new_count INTEGER DEFAULT 0,
                    changed_count INTEGER DEFAULT 0,
                    expired_count INTEGER DEFAULT 0,
                    source_error_count INTEGER DEFAULT 0,
                    report_path TEXT,
                    email_delivery_status TEXT
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source_id ON jobs(source_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_name)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_active ON jobs(active, last_seen_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_observations_job_id ON job_observations(job_id)"
            )

            conn.commit()

    def add_or_update_company(self, company_id: str, name: str, enabled: bool = True) -> None:
        """Add or update a company."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO companies (id, name, enabled)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (company_id, name, enabled),
            )
            conn.commit()

    def add_or_update_source(
        self,
        source_id: str,
        company_id: str,
        source_type: str,
        source_key: Optional[str] = None,
    ) -> None:
        """Add or update a source."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sources (id, company_id, source_type, source_key, enabled)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                    source_type = excluded.source_type,
                    source_key = excluded.source_key
                """,
                (source_id, company_id, source_type, source_key),
            )
            conn.commit()

    def save_job(self, job: NormalizedJob, source_id: str) -> None:
        """Save a normalized job to the database."""
        internal_id = self._generate_job_id(source_id, job.source_job_id)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            data = {
                "source_type": job.source_type,
                "source_company_id": job.source_company_id,
                "employment_type": job.employment_type.value,
                "remote_status": job.remote_status.value,
                "department": job.department,
                "team": job.team,
                "workplace_type": job.workplace_type,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "salary_currency": job.salary_currency,
                "salary_period": job.salary_period,
                "education_requirements": job.education_requirements,
                "experience_requirements": job.experience_requirements,
                "category": job.category,
                "entry_level_signal": job.entry_level_signal,
                "seniority_warning": job.seniority_warning,
                "location_match": job.location_match,
                "relocation_candidate": job.relocation_candidate,
                "remote_candidate": job.remote_candidate,
                "technical_relevance": job.technical_relevance,
                "trade_relevance": job.trade_relevance,
                "immediate_income_relevance": job.immediate_income_relevance,
                "warning_flags": job.warning_flags,
                "possible_duplicate_group": job.possible_duplicate_group,
                "duplicate_confidence": job.duplicate_confidence,
            }

            cursor.execute(
                """
                INSERT INTO jobs (
                    internal_id, source_id, source_job_id, company_name,
                    title, location, apply_url, source_url,
                    current_content_hash, first_seen_at, last_seen_at,
                    data_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, source_job_id) DO UPDATE SET
                    title = excluded.title,
                    location = excluded.location,
                    apply_url = excluded.apply_url,
                    current_content_hash = excluded.current_content_hash,
                    last_seen_at = excluded.last_seen_at,
                    data_json = excluded.data_json
                """,
                (
                    internal_id,
                    source_id,
                    job.source_job_id,
                    job.company_name,
                    job.title,
                    job.location,
                    job.apply_url,
                    job.source_url,
                    job.content_hash,
                    job.first_seen_at.isoformat(),
                    job.last_seen_at.isoformat(),
                    json.dumps(data),
                ),
            )
            conn.commit()

    def get_previous_jobs(self, source_id: str) -> dict[str, NormalizedJob]:
        """Get all previously seen jobs from a source."""
        jobs = {}
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT internal_id, source_job_id, data_json
                FROM jobs
                WHERE source_id = ? AND active = 1
                """,
                (source_id,),
            )

            for internal_id, source_job_id, data_json in cursor.fetchall():
                data = json.loads(data_json) if data_json else {}
                # Reconstruct minimal job for comparison
                jobs[source_job_id] = internal_id

        return jobs

    def mark_jobs_inactive(self, source_id: str, active_job_ids: set[str]) -> None:
        """Mark jobs as inactive if they're no longer in source results."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Get all job IDs for this source that were active
            cursor.execute(
                "SELECT source_job_id FROM jobs WHERE source_id = ? AND active = 1",
                (source_id,),
            )
            all_job_ids = {row[0] for row in cursor.fetchall()}

            # Find jobs to deactivate
            to_deactivate = all_job_ids - active_job_ids

            if to_deactivate:
                placeholders = ",".join("?" * len(to_deactivate))
                cursor.execute(
                    f"UPDATE jobs SET active = 0 WHERE source_id = ? AND source_job_id IN ({placeholders})",
                    [source_id] + list(to_deactivate),
                )
                conn.commit()

    @staticmethod
    def _generate_job_id(source_id: str, source_job_id: str) -> str:
        """Generate stable internal job ID."""
        return f"{source_id}#{source_job_id}"

    def update_source_status(
        self,
        source_id: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Update source collection status."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if status == "success":
                cursor.execute(
                    """
                    UPDATE sources
                    SET last_successful_at = CURRENT_TIMESTAMP,
                        last_status = ?,
                        last_error = NULL,
                        consecutive_failures = 0
                    WHERE id = ?
                    """,
                    (status, source_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE sources
                    SET last_attempted_at = CURRENT_TIMESTAMP,
                        last_status = ?,
                        last_error = ?,
                        consecutive_failures = consecutive_failures + 1
                    WHERE id = ?
                    """,
                    (status, error, source_id),
                )
            conn.commit()

    def create_run(self, run_id: str) -> None:
        """Create a new report run entry."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO report_runs (run_id, start_time, status)
                VALUES (?, CURRENT_TIMESTAMP, 'in_progress')
                """,
                (run_id,),
            )
            conn.commit()

    def close(self) -> None:
        """Close database connection."""
        pass
