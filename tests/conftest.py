"""Pytest configuration and fixtures."""
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from job_collector.models import EmploymentType, NormalizedJob, RemoteStatus


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield db_path


@pytest.fixture
def temp_config_dir():
    """Create temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_job():
    """Create a sample job for testing."""
    return NormalizedJob(
        source_type="greenhouse",
        source_company_id="example-company",
        source_job_id="12345",
        company_name="Example Company",
        title="Software Engineer",
        location="San Francisco, CA",
        apply_url="https://example.com/apply/12345",
        source_url="https://boards.greenhouse.io/example/jobs/12345",
        date_posted=datetime(2026, 7, 1),
        description_text="We are looking for a software engineer...",
        employment_type=EmploymentType.FULL_TIME,
        remote_status=RemoteStatus.HYBRID,
        salary_text="$100,000 - $150,000 per year",
        content_hash="abcd1234",
    )


@pytest.fixture
def sample_jobs():
    """Create multiple sample jobs for testing."""
    jobs = []

    # Software engineer role
    jobs.append(NormalizedJob(
        source_type="greenhouse",
        source_company_id="company1",
        source_job_id="1",
        company_name="Company One",
        title="Software Engineer",
        location="San Francisco, CA",
        apply_url="https://example.com/apply/1",
        source_url="https://boards.greenhouse.io/company1/jobs/1",
        employment_type=EmploymentType.FULL_TIME,
        remote_status=RemoteStatus.REMOTE,
        description_text="Looking for a software engineer",
        content_hash="hash1",
    ))

    # QA role
    jobs.append(NormalizedJob(
        source_type="lever",
        source_company_id="company2",
        source_job_id="2",
        company_name="Company Two",
        title="QA Engineer",
        location="Austin, TX",
        apply_url="https://example.com/apply/2",
        source_url="https://jobs.lever.co/company2/2",
        employment_type=EmploymentType.FULL_TIME,
        remote_status=RemoteStatus.ON_SITE,
        description_text="Looking for a QA engineer",
        content_hash="hash2",
    ))

    # IT Support role
    jobs.append(NormalizedJob(
        source_type="ashby",
        source_company_id="company3",
        source_job_id="3",
        company_name="Company Three",
        title="IT Support Specialist",
        location="Austin, TX",
        apply_url="https://example.com/apply/3",
        source_url="https://jobs.ashby.co/company3/3",
        employment_type=EmploymentType.FULL_TIME,
        remote_status=RemoteStatus.ON_SITE,
        description_text="Looking for IT support",
        content_hash="hash3",
    ))

    return jobs
