"""Tests for report generation."""
from pathlib import Path

import pytest

from job_collector.models import JobStatus, NormalizedJob
from job_collector.reporting import ReportGenerator


def test_generate_reports(tmp_path):
    """Should generate JSON and Markdown reports."""
    generator = ReportGenerator(tmp_path)

    jobs = [
        NormalizedJob(
            source_type="greenhouse",
            source_company_id="company1",
            source_job_id="1",
            company_name="Example Corp",
            title="Software Engineer",
            location="San Francisco, CA",
            apply_url="https://example.com/apply/1",
            source_url="https://example.com/jobs/1",
            description_text="Build great software",
            status=JobStatus.NEW,
        ),
        NormalizedJob(
            source_type="lever",
            source_company_id="company2",
            source_job_id="2",
            company_name="Another Corp",
            title="QA Engineer",
            location="Austin, TX",
            apply_url="https://example.com/apply/2",
            source_url="https://example.com/jobs/2",
            description_text="Test our products",
            status=JobStatus.CHANGED,
        ),
    ]

    run_stats = {
        "source_count": 5,
        "successful_sources": 4,
        "failed_sources": 1,
    }

    source_errors = [
        {"source": "company3 (jsonld)", "error": "Timeout"},
    ]

    json_path, md_path = generator.generate_reports(jobs, run_stats, source_errors)

    assert json_path.exists()
    assert md_path.exists()

    # Check JSON content
    import json
    with open(json_path) as f:
        json_report = json.load(f)

    assert "run" in json_report
    assert "jobs" in json_report
    assert json_report["run"]["source_count"] == 5
    assert json_report["run"]["successful_sources"] == 4

    # Check Markdown content
    with open(md_path) as f:
        md_content = f.read()

    assert "Job Collection Report" in md_content
    assert "Software Engineer" in md_content
    assert "QA Engineer" in md_content


def test_report_categorizes_jobs(tmp_path):
    """Should categorize jobs in markdown report."""
    generator = ReportGenerator(tmp_path)

    jobs = [
        NormalizedJob(
            source_type="greenhouse",
            source_company_id="c1",
            source_job_id="1",
            company_name="Company A",
            title="Software Developer",
            location="Remote",
            apply_url="https://example.com/1",
            source_url="https://example.com/1",
            status=JobStatus.NEW,
        ),
        NormalizedJob(
            source_type="lever",
            source_company_id="c2",
            source_job_id="2",
            company_name="Company B",
            title="IT Support",
            location="Austin, TX",
            apply_url="https://example.com/2",
            source_url="https://example.com/2",
            status=JobStatus.EXPIRED,
        ),
    ]

    json_path, md_path = generator.generate_reports(jobs, {}, [])

    with open(md_path) as f:
        content = f.read()

    # Should mention new jobs section and expired jobs
    assert "New" in content
    assert "Expired" in content


def test_report_handles_no_errors(tmp_path):
    """Should handle reports with no source errors."""
    generator = ReportGenerator(tmp_path)

    json_path, md_path = generator.generate_reports([], {}, [])

    assert json_path.exists()
    assert md_path.exists()

    import json
    with open(json_path) as f:
        report = json.load(f)

    assert report["source_errors"] == []


def test_email_format():
    """Should format email correctly."""
    email_body = ReportGenerator._format_job_md(NormalizedJob(
        source_type="test",
        source_company_id="c1",
        source_job_id="1",
        company_name="Test Corp",
        title="Engineer",
        location="San Francisco, CA",
        apply_url="https://example.com/apply/1",
        source_url="https://example.com/jobs/1",
        description_text="Test job",
    ))

    assert isinstance(email_body, list)
    assert "Engineer" in str(email_body)
    assert "Test Corp" in str(email_body)
    assert "San Francisco" in str(email_body)
