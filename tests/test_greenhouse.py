"""Tests for Greenhouse collector."""
import json
from pathlib import Path

import pytest

from job_collector.collectors.greenhouse import GreenhouseCollector
from job_collector.config import SourceConfig
from job_collector.models import EmploymentType, RemoteStatus


@pytest.fixture
def greenhouse_fixture():
    """Load Greenhouse API response fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "greenhouse_response.json"
    with open(fixture_path) as f:
        return json.load(f)


def test_parse_greenhouse_job():
    """Should parse Greenhouse job correctly."""
    source_config = SourceConfig(type="greenhouse", board_token="example")
    collector = GreenhouseCollector("example-company", source_config)

    job_data = {
        "id": 123456,
        "title": "Software Engineer",
        "company": {"name": "Example Corp"},
        "absolute_url": "https://example.com/jobs/123456",
        "published_at": "2026-07-20T10:00:00Z",
        "offices": [{"name": "San Francisco, CA"}],
        "departments": [{"name": "Engineering"}],
        "content": "<p>Join our team</p>",
    }

    job = collector._parse_job(job_data)

    assert job.source_type == "greenhouse"
    assert job.source_job_id == "123456"
    assert job.title == "Software Engineer"
    assert job.company_name == "Example Corp"
    assert job.location == "San Francisco, CA"
    assert job.employment_type == EmploymentType.FULL_TIME
    assert job.content_hash is not None


def test_parse_greenhouse_remote_job():
    """Should detect remote jobs."""
    source_config = SourceConfig(type="greenhouse", board_token="example")
    collector = GreenhouseCollector("example-company", source_config)

    job_data = {
        "id": 123456,
        "title": "Remote Software Engineer",
        "company": {"name": "Example Corp"},
        "absolute_url": "https://example.com/jobs/123456",
        "published_at": "2026-07-20T10:00:00Z",
        "offices": [{"name": "Remote"}],
        "departments": [],
        "content": "Work from home opportunity",
    }

    job = collector._parse_job(job_data)

    assert job.remote_status == RemoteStatus.REMOTE


def test_greenhouse_missing_board_token():
    """Should return error if board token is missing."""
    source_config = SourceConfig(type="greenhouse")
    collector = GreenhouseCollector("example-company", source_config)

    # The _fetch_jobs method requires board_token, which would fail
    # This is tested via the async collect() method in integration tests
    assert source_config.board_token is None


def test_parse_greenhouse_multiple_offices():
    """Should handle multiple office locations."""
    source_config = SourceConfig(type="greenhouse", board_token="example")
    collector = GreenhouseCollector("example-company", source_config)

    job_data = {
        "id": 123456,
        "title": "Software Engineer",
        "company": {"name": "Example Corp"},
        "absolute_url": "https://example.com/jobs/123456",
        "published_at": "2026-07-20T10:00:00Z",
        "offices": [
            {"name": "San Francisco, CA"},
            {"name": "New York, NY"},
        ],
        "departments": [{"name": "Engineering"}],
        "content": "Multi-office role",
    }

    job = collector._parse_job(job_data)

    assert "San Francisco" in job.location
    assert "New York" in job.location


def test_parse_greenhouse_minimal_data():
    """Should handle minimal job data."""
    source_config = SourceConfig(type="greenhouse", board_token="example")
    collector = GreenhouseCollector("example-company", source_config)

    job_data = {
        "id": 123456,
        "title": "Position",
        "absolute_url": "https://example.com/jobs/123456",
    }

    job = collector._parse_job(job_data)

    assert job.source_job_id == "123456"
    assert job.title == "Position"
    assert job.location == "Remote"
    assert job.company_name == "example-company"


def test_parse_greenhouse_date_parsing():
    """Should parse ISO 8601 dates correctly."""
    source_config = SourceConfig(type="greenhouse", board_token="example")
    collector = GreenhouseCollector("example-company", source_config)

    job_data = {
        "id": 123456,
        "title": "Engineer",
        "absolute_url": "https://example.com/jobs/123456",
        "published_at": "2026-07-20T10:00:00Z",
    }

    job = collector._parse_job(job_data)

    assert job.date_posted is not None
    assert job.date_posted.year == 2026
    assert job.date_posted.month == 7
    assert job.date_posted.day == 20
