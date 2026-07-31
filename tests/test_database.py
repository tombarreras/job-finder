"""Tests for database functionality."""
from pathlib import Path

import pytest

from job_collector.database import JobDatabase
from job_collector.models import EmploymentType, NormalizedJob, RemoteStatus


def test_database_initialization(temp_db):
    """Database should initialize with proper schema."""
    db = JobDatabase(temp_db)
    assert temp_db.exists()

    # Check that tables exist
    import sqlite3
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}

        assert "companies" in tables
        assert "sources" in tables
        assert "jobs" in tables
        assert "job_observations" in tables
        assert "report_runs" in tables


def test_save_and_retrieve_company(temp_db):
    """Should save and retrieve company."""
    db = JobDatabase(temp_db)
    db.add_or_update_company("test-company", "Test Company", True)

    import sqlite3
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, enabled FROM companies WHERE id = ?", ("test-company",))
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "test-company"
        assert row[1] == "Test Company"
        assert row[2] == 1


def test_save_and_retrieve_source(temp_db):
    """Should save and retrieve source."""
    db = JobDatabase(temp_db)
    db.add_or_update_company("test-company", "Test Company", True)
    db.add_or_update_source(
        "source-1",
        "test-company",
        "greenhouse",
        "test-board",
    )

    import sqlite3
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, source_type, source_key FROM sources WHERE id = ?",
            ("source-1",),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "source-1"
        assert row[1] == "greenhouse"
        assert row[2] == "test-board"


def test_save_job(temp_db, sample_job):
    """Should save job to database."""
    db = JobDatabase(temp_db)
    db.add_or_update_company("example-company", "Example Company", True)
    db.add_or_update_source("source-1", "example-company", "greenhouse", "example")

    db.save_job(sample_job, "source-1")

    import sqlite3
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title, company_name, source_job_id FROM jobs WHERE source_id = ?",
            ("source-1",),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "Software Engineer"
        assert row[1] == "Example Company"
        assert row[2] == "12345"


def test_update_source_status(temp_db):
    """Should update source collection status."""
    db = JobDatabase(temp_db)
    db.add_or_update_company("test-company", "Test Company", True)
    db.add_or_update_source("source-1", "test-company", "greenhouse", "test")

    db.update_source_status("source-1", "success")

    import sqlite3
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_status, consecutive_failures FROM sources WHERE id = ?",
            ("source-1",),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "success"
        assert row[1] == 0


def test_update_source_status_failure(temp_db):
    """Should track consecutive failures."""
    db = JobDatabase(temp_db)
    db.add_or_update_company("test-company", "Test Company", True)
    db.add_or_update_source("source-1", "test-company", "greenhouse", "test")

    db.update_source_status("source-1", "error", "Connection timeout")
    db.update_source_status("source-1", "error", "Connection timeout")

    import sqlite3
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT consecutive_failures FROM sources WHERE id = ?",
            ("source-1",),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == 2


def test_mark_jobs_inactive(temp_db, sample_job):
    """Should mark jobs as inactive when not in current results."""
    db = JobDatabase(temp_db)
    db.add_or_update_company("example-company", "Example Company", True)
    db.add_or_update_source("source-1", "example-company", "greenhouse", "example")

    db.save_job(sample_job, "source-1")

    # Mark jobs as inactive
    db.mark_jobs_inactive("source-1", set())  # Empty set of active jobs

    import sqlite3
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT active FROM jobs WHERE source_id = ?", ("source-1",))
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == 0  # Should be inactive


def test_create_run(temp_db):
    """Should create a report run entry."""
    db = JobDatabase(temp_db)
    db.create_run("run-1")

    import sqlite3
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM report_runs WHERE run_id = ?", ("run-1",))
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "in_progress"
