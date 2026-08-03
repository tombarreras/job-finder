"""Tests for Lever collector."""
import json
from pathlib import Path

import pytest

from job_collector.collectors.lever import LeverCollector
from job_collector.config import SourceConfig
from job_collector.models import EmploymentType, RemoteStatus


@pytest.fixture
def lever_fixture():
    """Load Lever API response fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "lever_response.json"
    with open(fixture_path) as f:
        return json.load(f)


def test_parse_lever_job():
    """Should parse Lever job correctly."""
    source_config = SourceConfig(type="lever", board_name="example")
    collector = LeverCollector("example-company", source_config)

    job_data = {
        "id": "abc123",
        "text": "Full Stack Developer",
        "description": "<p>Join our team</p>",
        "applyUrl": "https://jobs.lever.co/example/abc123",
        "url": "https://jobs.lever.co/example/full-stack-developer",
        "createdAt": 1721476800000,
        "locations": [{"name": "Austin, TX"}],
        "department": {"name": "Engineering"},
        "team": {"name": "Platform"},
        "workplaceType": "Hybrid",
    }

    job = collector._parse_job(job_data)

    assert job.source_type == "lever"
    assert job.source_job_id == "abc123"
    assert job.title == "Full Stack Developer"
    assert job.location == "Austin, TX"
    assert job.remote_status == RemoteStatus.HYBRID
    assert job.department == "Engineering"
    assert job.team == "Platform"


def test_parse_lever_remote_job():
    """Should detect remote workplace type."""
    source_config = SourceConfig(type="lever", board_name="example")
    collector = LeverCollector("example-company", source_config)

    job_data = {
        "id": "def456",
        "text": "Remote Engineer",
        "description": "Work from anywhere",
        "applyUrl": "https://jobs.lever.co/example/def456",
        "url": "https://jobs.lever.co/example/remote-engineer",
        "createdAt": 1721563200000,
        "locations": [{"name": "Remote"}],
        "workplaceType": "Remote",
    }

    job = collector._parse_job(job_data)

    assert job.remote_status == RemoteStatus.REMOTE
    assert job.location == "Remote"


def test_parse_lever_employment_types():
    """Should parse different employment types."""
    source_config = SourceConfig(type="lever", board_name="example")
    collector = LeverCollector("example-company", source_config)

    # Full-time
    job_data = {
        "id": "1",
        "text": "FT Job",
        "applyUrl": "https://example.com/1",
        "url": "https://example.com/1",
        "createdAt": 1721476800000,
        "workplaceType": "Full-time",
    }
    job = collector._parse_job(job_data)
    assert job.employment_type == EmploymentType.FULL_TIME

    # Part-time
    job_data["workplaceType"] = "Part-time"
    job = collector._parse_job(job_data)
    assert job.employment_type == EmploymentType.PART_TIME

    # Contract
    job_data["workplaceType"] = "Contract"
    job = collector._parse_job(job_data)
    assert job.employment_type == EmploymentType.CONTRACT


def test_parse_lever_multiple_locations():
    """Should handle multiple locations."""
    source_config = SourceConfig(type="lever", board_name="example")
    collector = LeverCollector("example-company", source_config)

    job_data = {
        "id": "xyz789",
        "text": "Engineer",
        "applyUrl": "https://jobs.lever.co/example/xyz789",
        "url": "https://jobs.lever.co/example/engineer",
        "createdAt": 1721476800000,
        "locations": [
            {"name": "San Francisco, CA"},
            {"name": "New York, NY"},
        ],
    }

    job = collector._parse_job(job_data)

    # Should use first location
    assert "San Francisco" in job.location


def test_parse_lever_date_from_timestamp():
    """Should convert Lever timestamp to datetime."""
    source_config = SourceConfig(type="lever", board_name="example")
    collector = LeverCollector("example-company", source_config)

    job_data = {
        "id": "abc123",
        "text": "Engineer",
        "applyUrl": "https://example.com/abc123",
        "url": "https://example.com/abc123",
        "createdAt": 1784548800000,  # 2026-07-20 12:00:00 UTC
    }

    job = collector._parse_job(job_data)

    assert job.date_posted is not None
    assert job.date_posted.year == 2026
    assert job.date_posted.month == 7


def test_parse_lever_minimal_data():
    """Should handle minimal job data."""
    source_config = SourceConfig(type="lever", board_name="example")
    collector = LeverCollector("example-company", source_config)

    job_data = {
        "id": "abc123",
        "text": "Position",
        "applyUrl": "https://jobs.lever.co/example/abc123",
        "url": "https://jobs.lever.co/example/position",
        "createdAt": 1721476800000,
    }

    job = collector._parse_job(job_data)

    assert job.source_job_id == "abc123"
    assert job.title == "Position"
    assert job.location == "Remote"
    assert job.remote_status == RemoteStatus.UNKNOWN
