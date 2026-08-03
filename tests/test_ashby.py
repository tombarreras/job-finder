"""Tests for Ashby collector."""
import json
from pathlib import Path

import pytest

from job_collector.collectors.ashby import AshbyCollector
from job_collector.config import SourceConfig
from job_collector.models import EmploymentType, RemoteStatus


@pytest.fixture
def ashby_fixture():
    """Load Ashby API response fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "ashby_response.json"
    with open(fixture_path) as f:
        return json.load(f)


def test_parse_ashby_job():
    """Should parse Ashby job correctly."""
    source_config = SourceConfig(type="ashby", board_name="example")
    collector = AshbyCollector("example-company", source_config)

    job_data = {
        "id": "xy789",
        "title": "Data Engineer",
        "description": "<p>Build data infrastructure</p>",
        "descriptionPlain": "Build data infrastructure",
        "url": "https://jobs.ashby.co/example/data-engineer",
        "applyUrl": "https://jobs.ashby.co/example/data-engineer/apply",
        "createdAt": "2026-07-22T08:00:00Z",
        "location": {
            "city": "San Francisco",
            "state": "CA",
            "country": "USA",
        },
        "department": {"name": "Engineering"},
        "team": {"name": "Data"},
        "employmentType": "Full-time",
        "isRemote": False,
        "isHybrid": True,
        "workplaceType": "Hybrid",
        "compensation": {
            "min": 120000,
            "max": 160000,
            "currency": "USD",
            "period": "year",
        },
    }

    job = collector._parse_job(job_data)

    assert job.source_type == "ashby"
    assert job.source_job_id == "xy789"
    assert job.title == "Data Engineer"
    assert job.location == "San Francisco, CA"
    assert job.remote_status == RemoteStatus.HYBRID
    assert job.employment_type == EmploymentType.FULL_TIME
    assert job.salary_min == 120000
    assert job.salary_max == 160000
    assert job.salary_text == "$120,000 - $160,000 year"


def test_parse_ashby_remote_job():
    """Should detect remote status."""
    source_config = SourceConfig(type="ashby", board_name="example")
    collector = AshbyCollector("example-company", source_config)

    job_data = {
        "id": "uv456",
        "title": "Remote Engineer",
        "url": "https://jobs.ashby.co/example/remote-engineer",
        "applyUrl": "https://jobs.ashby.co/example/remote-engineer/apply",
        "createdAt": "2026-07-25T14:00:00Z",
        "location": {"city": "Remote", "country": "USA"},
        "isRemote": True,
        "isHybrid": False,
        "workplaceType": "Remote",
        "compensation": {
            "min": 100000,
            "max": 130000,
            "currency": "USD",
            "period": "year",
        },
    }

    job = collector._parse_job(job_data)

    assert job.remote_status == RemoteStatus.REMOTE
    assert job.location == "Remote"


def test_parse_ashby_employment_types():
    """Should parse different employment types."""
    source_config = SourceConfig(type="ashby", board_name="example")
    collector = AshbyCollector("example-company", source_config)

    base_data = {
        "id": "1",
        "title": "Position",
        "url": "https://example.com/1",
        "applyUrl": "https://example.com/1",
        "createdAt": "2026-07-20T00:00:00Z",
    }

    # Full-time
    data = {**base_data, "employmentType": "Full-time"}
    job = collector._parse_job(data)
    assert job.employment_type == EmploymentType.FULL_TIME

    # Part-time
    data = {**base_data, "employmentType": "Part-time"}
    job = collector._parse_job(data)
    assert job.employment_type == EmploymentType.PART_TIME

    # Contract
    data = {**base_data, "employmentType": "Contract"}
    job = collector._parse_job(data)
    assert job.employment_type == EmploymentType.CONTRACT

    # Temporary
    data = {**base_data, "employmentType": "Temporary"}
    job = collector._parse_job(data)
    assert job.employment_type == EmploymentType.TEMPORARY


def test_parse_ashby_location_formats():
    """Should handle different location formats."""
    source_config = SourceConfig(type="ashby", board_name="example")
    collector = AshbyCollector("example-company", source_config)

    base_data = {
        "id": "1",
        "title": "Position",
        "url": "https://example.com/1",
        "applyUrl": "https://example.com/1",
        "createdAt": "2026-07-20T00:00:00Z",
    }

    # Complete location
    data = {
        **base_data,
        "location": {
            "city": "San Francisco",
            "state": "CA",
            "country": "USA",
        },
    }
    job = collector._parse_job(data)
    # The US country suffix is dropped as noise; see test_parse_ashby_job.
    assert job.location == "San Francisco, CA"

    # Non-US country is kept
    data = {
        **base_data,
        "location": {
            "city": "Berlin",
            "country": "Germany",
        },
    }
    job = collector._parse_job(data)
    assert job.location == "Berlin, Germany"

    # Partial location
    data = {
        **base_data,
        "location": {
            "city": "Austin",
            "state": "TX",
        },
    }
    job = collector._parse_job(data)
    assert job.location == "Austin, TX"


def test_parse_ashby_salary():
    """Should parse salary correctly."""
    source_config = SourceConfig(type="ashby", board_name="example")
    collector = AshbyCollector("example-company", source_config)

    job_data = {
        "id": "1",
        "title": "Engineer",
        "url": "https://example.com/1",
        "applyUrl": "https://example.com/1",
        "createdAt": "2026-07-20T00:00:00Z",
        "compensation": {
            "min": 100000,
            "max": 150000,
            "currency": "EUR",
            "period": "year",
        },
    }

    job = collector._parse_job(job_data)

    assert job.salary_min == 100000
    assert job.salary_max == 150000
    assert job.salary_currency == "EUR"
    assert "$100,000 - $150,000" in job.salary_text


def test_parse_ashby_minimal_data():
    """Should handle minimal job data."""
    source_config = SourceConfig(type="ashby", board_name="example")
    collector = AshbyCollector("example-company", source_config)

    job_data = {
        "id": "xyz789",
        "title": "Position",
        "url": "https://example.com/position",
        "applyUrl": "https://example.com/position/apply",
        "createdAt": "2026-07-20T00:00:00Z",
    }

    job = collector._parse_job(job_data)

    assert job.source_job_id == "xyz789"
    assert job.title == "Position"
    assert job.location == "Remote"
    assert job.remote_status == RemoteStatus.UNKNOWN


def test_parse_ashby_date_parsing():
    """Should parse ISO 8601 dates."""
    source_config = SourceConfig(type="ashby", board_name="example")
    collector = AshbyCollector("example-company", source_config)

    job_data = {
        "id": "1",
        "title": "Engineer",
        "url": "https://example.com/1",
        "applyUrl": "https://example.com/1",
        "createdAt": "2026-07-20T10:30:00Z",
    }

    job = collector._parse_job(job_data)

    assert job.date_posted is not None
    assert job.date_posted.year == 2026
    assert job.date_posted.month == 7
    assert job.date_posted.day == 20
    assert job.date_posted.hour == 10
