"""Tests for JSON-LD collector."""
from pathlib import Path

import pytest

from job_collector.collectors.jsonld import JSONLDCollector
from job_collector.config import SourceConfig
from job_collector.models import RemoteStatus


def test_extract_json_ld_blocks():
    """Should extract JSON-LD blocks from HTML."""
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {"@type": "JobPosting", "title": "Job 1"}
        </script>
        <script type="application/ld+json">
        {"@type": "JobPosting", "title": "Job 2"}
        </script>
    </head>
    </html>
    """

    blocks = JSONLDCollector._extract_json_ld_blocks(html)

    assert len(blocks) == 2
    assert blocks[0]["title"] == "Job 1"
    assert blocks[1]["title"] == "Job 2"


def test_extract_json_ld_with_graph():
    """Should extract JSON-LD @graph blocks."""
    html = """
    <script type="application/ld+json">
    {
      "@graph": [
        {"@type": "JobPosting", "title": "Job 1"},
        {"@type": "Organization", "name": "Company"}
      ]
    }
    </script>
    """

    blocks = JSONLDCollector._extract_json_ld_blocks(html)

    assert len(blocks) == 1
    assert "@graph" in blocks[0]
    assert len(blocks[0]["@graph"]) == 2


def test_parse_json_ld_job():
    """Should parse JSON-LD JobPosting."""
    source_config = SourceConfig(type="jsonld", site_url="https://example.com/careers")
    collector = JSONLDCollector("example-company", source_config)

    job_data = {
        "@type": "JobPosting",
        "title": "Senior DevOps Engineer",
        "description": "Build and maintain infrastructure",
        "hiringOrganization": {"@type": "Organization", "name": "Example Corp"},
        "url": "https://example.com/careers/devops",
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "San Francisco",
                "addressRegion": "CA",
                "addressCountry": "USA",
            },
        },
        "employmentType": "FULL_TIME",
        "jobLocationType": "HYBRID",
        "baseSalary": {
            "@type": "PriceSpecification",
            "currency": "USD",
            "minValue": 150000,
            "maxValue": 200000,
        },
        "datePosted": "2026-07-20T10:00:00Z",
    }

    job = collector._parse_job(job_data)

    assert job is not None
    assert job.source_type == "jsonld"
    assert job.title == "Senior DevOps Engineer"
    assert job.company_name == "Example Corp"
    assert job.location == "San Francisco, CA"
    assert job.remote_status == RemoteStatus.HYBRID
    assert job.salary_min == 150000
    assert job.salary_max == 200000


def test_parse_json_ld_remote_job():
    """Should detect remote status."""
    source_config = SourceConfig(type="jsonld", site_url="https://example.com")
    collector = JSONLDCollector("example-company", source_config)

    job_data = {
        "@type": "JobPosting",
        "title": "Remote Engineer",
        "hiringOrganization": {"@type": "Organization", "name": "Company"},
        "url": "https://example.com/remote-job",
        "jobLocationType": "REMOTE",
    }

    job = collector._parse_job(job_data)

    assert job.remote_status == RemoteStatus.REMOTE


def test_parse_json_ld_on_site_job():
    """Should detect on-site status."""
    source_config = SourceConfig(type="jsonld", site_url="https://example.com")
    collector = JSONLDCollector("example-company", source_config)

    job_data = {
        "@type": "JobPosting",
        "title": "On-Site Role",
        "hiringOrganization": {"@type": "Organization", "name": "Company"},
        "url": "https://example.com/on-site-job",
        "jobLocationType": "ON_SITE",
    }

    job = collector._parse_job(job_data)

    assert job.remote_status == RemoteStatus.ON_SITE


def test_parse_json_ld_multiple_locations():
    """Should handle multiple job locations."""
    source_config = SourceConfig(type="jsonld", site_url="https://example.com")
    collector = JSONLDCollector("example-company", source_config)

    job_data = {
        "@type": "JobPosting",
        "title": "Engineer",
        "hiringOrganization": {"@type": "Organization", "name": "Company"},
        "url": "https://example.com/job",
        "jobLocation": [
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "San Francisco",
                    "addressRegion": "CA",
                },
            },
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "New York",
                    "addressRegion": "NY",
                },
            },
        ],
    }

    job = collector._parse_job(job_data)

    # Should use first location
    assert "San Francisco" in job.location


def test_parse_json_ld_minimal_data():
    """Should handle minimal job data."""
    source_config = SourceConfig(type="jsonld", site_url="https://example.com")
    collector = JSONLDCollector("example-company", source_config)

    job_data = {
        "@type": "JobPosting",
        "title": "Position",
        "url": "https://example.com/position",
    }

    job = collector._parse_job(job_data)

    assert job is not None
    assert job.title == "Position"
    assert job.location == "Remote"


def test_parse_json_ld_no_title():
    """Should return None if title is missing."""
    source_config = SourceConfig(type="jsonld", site_url="https://example.com")
    collector = JSONLDCollector("example-company", source_config)

    job_data = {
        "@type": "JobPosting",
        "url": "https://example.com/position",
    }

    job = collector._parse_job(job_data)

    assert job is None


def test_parse_json_ld_date_parsing():
    """Should parse ISO 8601 dates."""
    source_config = SourceConfig(type="jsonld", site_url="https://example.com")
    collector = JSONLDCollector("example-company", source_config)

    job_data = {
        "@type": "JobPosting",
        "title": "Engineer",
        "url": "https://example.com/job",
        "datePosted": "2026-07-20T10:00:00Z",
    }

    job = collector._parse_job(job_data)

    assert job.date_posted is not None
    assert job.date_posted.year == 2026
    assert job.date_posted.month == 7


def test_parse_json_ld_salary():
    """Should parse salary information."""
    source_config = SourceConfig(type="jsonld", site_url="https://example.com")
    collector = JSONLDCollector("example-company", source_config)

    job_data = {
        "@type": "JobPosting",
        "title": "Engineer",
        "url": "https://example.com/job",
        "baseSalary": {
            "@type": "PriceSpecification",
            "currency": "USD",
            "minValue": 80000,
            "maxValue": 120000,
        },
    }

    job = collector._parse_job(job_data)

    assert job.salary_min == 80000
    assert job.salary_max == 120000
    assert "$80,000 - $120,000" in job.salary_text


def test_parse_json_ld_string_organization():
    """Should handle string organization name."""
    source_config = SourceConfig(type="jsonld", site_url="https://example.com")
    collector = JSONLDCollector("example-company", source_config)

    job_data = {
        "@type": "JobPosting",
        "title": "Engineer",
        "url": "https://example.com/job",
        "hiringOrganization": "Example Corp",
    }

    job = collector._parse_job(job_data)

    assert job.company_name == "Example Corp"
