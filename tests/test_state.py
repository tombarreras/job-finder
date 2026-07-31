"""Tests for state management."""
from pathlib import Path

import pytest

from job_collector.database import JobDatabase
from job_collector.models import JobStatus, NormalizedJob
from job_collector.state import StateManager


def test_detect_new_job(temp_db):
    """Should detect new jobs."""
    db = JobDatabase(temp_db)
    state_mgr = StateManager(db)

    # Add company and source first
    db.add_or_update_company("test", "Test", True)
    db.add_or_update_source("source-1", "test", "test", "test")

    job = NormalizedJob(
        source_type="test",
        source_company_id="test",
        source_job_id="job1",
        company_name="Test Co",
        title="Engineer",
        location="Austin, TX",
        apply_url="https://example.com/apply/1",
        source_url="https://example.com/jobs/1",
        content_hash="abc123",
    )

    detected_job, reason = state_mgr.detect_status(job, "source-1")

    assert detected_job.status == JobStatus.NEW
    assert reason == "new"


def test_detect_unchanged_job(temp_db, sample_job):
    """Should detect unchanged jobs."""
    db = JobDatabase(temp_db)
    state_mgr = StateManager(db)

    # Add company and source
    db.add_or_update_company("example-company", "Example Company", True)
    db.add_or_update_source("source-1", "example-company", "test", "test")

    # Save initial job
    sample_job.status = JobStatus.NEW
    db.save_job(sample_job, "source-1")

    # Check same job with same hash
    new_job = NormalizedJob(
        source_type="test",
        source_company_id="example-company",
        source_job_id=sample_job.source_job_id,
        company_name=sample_job.company_name,
        title=sample_job.title,
        location=sample_job.location,
        apply_url=sample_job.apply_url,
        source_url=sample_job.source_url,
        content_hash=sample_job.content_hash,
    )

    detected_job, reason = state_mgr.detect_status(new_job, "source-1")

    assert detected_job.status == JobStatus.UNCHANGED
    assert reason == "unchanged"


def test_detect_changed_job(temp_db, sample_job):
    """Should detect changed jobs."""
    db = JobDatabase(temp_db)
    state_mgr = StateManager(db)

    # Add company and source
    db.add_or_update_company("example-company", "Example Company", True)
    db.add_or_update_source("source-1", "example-company", "test", "test")

    # Save initial job
    sample_job.status = JobStatus.NEW
    db.save_job(sample_job, "source-1")

    # Update same job with different content hash
    new_job = NormalizedJob(
        source_type="test",
        source_company_id="example-company",
        source_job_id=sample_job.source_job_id,
        company_name=sample_job.company_name,
        title="New Title",  # Changed title
        location=sample_job.location,
        apply_url=sample_job.apply_url,
        source_url=sample_job.source_url,
        content_hash="different_hash_123",  # Different hash
    )

    detected_job, reason = state_mgr.detect_status(new_job, "source-1")

    assert detected_job.status == JobStatus.CHANGED
    assert reason == "changed"


def test_detect_expired_jobs(temp_db, sample_job):
    """Should detect expired jobs."""
    db = JobDatabase(temp_db)
    state_mgr = StateManager(db)

    # Add company and source
    db.add_or_update_company("example-company", "Example Company", True)
    db.add_or_update_source("source-1", "example-company", "test", "test")

    # Save initial job
    db.save_job(sample_job, "source-1")

    # Detect expiration with empty active set
    expired = state_mgr.detect_expired_jobs("source-1", set())

    assert len(expired) == 1
    assert expired[0] == sample_job.source_job_id


def test_detect_reopened_job(temp_db, sample_job):
    """Should detect reopened jobs."""
    db = JobDatabase(temp_db)
    state_mgr = StateManager(db)

    # Add company and source
    db.add_or_update_company("example-company", "Example Company", True)
    db.add_or_update_source("source-1", "example-company", "test", "test")

    # Save and expire job
    db.save_job(sample_job, "source-1")
    state_mgr.detect_expired_jobs("source-1", set())

    # Job reappears with same hash
    new_job = NormalizedJob(
        source_type="test",
        source_company_id="example-company",
        source_job_id=sample_job.source_job_id,
        company_name=sample_job.company_name,
        title=sample_job.title,
        location=sample_job.location,
        apply_url=sample_job.apply_url,
        source_url=sample_job.source_url,
        content_hash=sample_job.content_hash,
    )

    detected_job, reason = state_mgr.detect_status(new_job, "source-1")

    assert detected_job.status == JobStatus.REOPENED
    assert reason == "reopened"


def test_calculate_statistics():
    """Should calculate correct statistics."""
    state_mgr = StateManager(None)

    jobs = [
        NormalizedJob(
            source_type="test", source_company_id="co", source_job_id="1",
            company_name="", title="", location="", apply_url="", source_url="",
            status=JobStatus.NEW
        ),
        NormalizedJob(
            source_type="test", source_company_id="co", source_job_id="2",
            company_name="", title="", location="", apply_url="", source_url="",
            status=JobStatus.CHANGED
        ),
        NormalizedJob(
            source_type="test", source_company_id="co", source_job_id="3",
            company_name="", title="", location="", apply_url="", source_url="",
            status=JobStatus.UNCHANGED
        ),
    ]

    stats = state_mgr.calculate_run_statistics(jobs)

    assert stats["new"] == 1
    assert stats["changed"] == 1
    assert stats["unchanged"] == 1
    assert stats["total"] == 3
