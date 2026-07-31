"""Tests for job deduplication."""
import pytest

from job_collector.deduplication import (
    find_cross_source_duplicates,
    find_exact_duplicate,
)
from job_collector.models import NormalizedJob


def test_find_exact_duplicate(sample_jobs):
    """Should find exact duplicate from same source."""
    job1 = sample_jobs[0]  # greenhouse
    job2 = NormalizedJob(
        source_type="greenhouse",
        source_company_id="company1",
        source_job_id="1",  # Same ID
        company_name="Company One",
        title="Software Engineer",
        location="San Francisco, CA",
        apply_url="https://example.com/apply/1",
        source_url="https://boards.greenhouse.io/company1/jobs/1",
    )

    existing = {"1": job1}
    duplicate = find_exact_duplicate(job2, existing)
    assert duplicate is not None
    assert duplicate.source_job_id == "1"


def test_find_no_exact_duplicate(sample_jobs):
    """Should not find duplicate with different ID."""
    job1 = sample_jobs[0]
    job2 = NormalizedJob(
        source_type="greenhouse",
        source_company_id="company1",
        source_job_id="999",  # Different ID
        company_name="Company One",
        title="Software Engineer",
        location="San Francisco, CA",
        apply_url="https://example.com/apply/1",
        source_url="https://boards.greenhouse.io/company1/jobs/1",
    )

    existing = {"1": job1}
    duplicate = find_exact_duplicate(job2, existing)
    assert duplicate is None


def test_find_cross_source_duplicate(sample_jobs):
    """Should find duplicate across different sources."""
    job1 = sample_jobs[0]  # greenhouse, Company One

    # Same job posted on Lever
    job2 = NormalizedJob(
        source_type="lever",
        source_company_id="company1",
        source_job_id="company1-lever-1",
        company_name="Company One",
        title="Software Engineer",
        location="San Francisco, CA",
        apply_url="https://example.com/apply/1",
        source_url="https://jobs.lever.co/company1/1",
    )

    duplicates = find_cross_source_duplicates(job2, [job1])
    assert len(duplicates) > 0
    assert duplicates[0][0].source_job_id == "1"


def test_cross_source_duplicate_high_confidence(sample_jobs):
    """Exact matches across sources should have high confidence."""
    job1 = sample_jobs[0]
    job2 = NormalizedJob(
        source_type="lever",
        source_company_id="company1",
        source_job_id="company1-lever-1",
        company_name="Company One",
        title="Software Engineer",
        location="San Francisco, CA",
        apply_url="https://example.com/apply/1",
        source_url="https://jobs.lever.co/company1/1",
    )

    duplicates = find_cross_source_duplicates(job2, [job1], threshold=0.7)
    assert len(duplicates) > 0
    assert duplicates[0][1] >= 0.7  # Confidence score


def test_no_cross_source_duplicate_different_company():
    """Different companies should not be considered duplicates."""
    job1 = NormalizedJob(
        source_type="greenhouse",
        source_company_id="google",
        source_job_id="1",
        company_name="Google",
        title="Software Engineer",
        location="San Francisco, CA",
        apply_url="https://google.com/apply/1",
        source_url="https://greenhouse.io/google/1",
    )

    job2 = NormalizedJob(
        source_type="lever",
        source_company_id="facebook",
        source_job_id="1",
        company_name="Meta",
        title="Software Engineer",
        location="San Francisco, CA",
        apply_url="https://meta.com/apply/1",
        source_url="https://lever.co/meta/1",
    )

    duplicates = find_cross_source_duplicates(job2, [job1], threshold=0.9)
    # Should not find high-confidence duplicates
    high_confidence = [d for d in duplicates if d[1] >= 0.9]
    assert len(high_confidence) == 0
