"""Tests for splitting a backlog across several emails."""
import pytest

from job_collector.email_delivery import EmailDelivery
from job_collector.models import EmploymentType, JobStatus, NormalizedJob, RemoteStatus


def make_job(i: int, desc_chars: int = 800) -> NormalizedJob:
    return NormalizedJob(
        source_type="workday",
        source_company_id="acme",
        source_job_id=f"R{i}",
        company_name="Acme",
        title=f"Role {i}",
        location="Austin, TX",
        apply_url=f"https://example.com/{i}",
        source_url=f"https://example.com/{i}",
        description_text="d" * desc_chars,
        employment_type=EmploymentType.FULL_TIME,
        remote_status=RemoteStatus.UNKNOWN,
        status=JobStatus.NEW,
    )


def test_every_job_appears_exactly_once():
    """Batching must not drop or duplicate jobs."""
    jobs = [make_job(i) for i in range(300)]

    batches = EmailDelivery.split_into_batches(jobs)

    flattened = [j.source_job_id for b in batches for j in b]
    assert len(flattened) == 300
    assert len(set(flattened)) == 300


def test_each_batch_fits_the_body_budget():
    """No batch may produce a body Gmail would clip."""
    jobs = [make_job(i) for i in range(300)]

    for index, batch in enumerate(EmailDelivery.split_into_batches(jobs), start=1):
        body = EmailDelivery.format_report_email(
            new_count=len(jobs), changed_count=0, expired_count=0, failed_sources=0,
            jobs=batch, total_active=len(jobs), part=index, total_parts=99,
        )
        assert len(body.encode("utf-8")) <= EmailDelivery.MAX_BODY_BYTES
        # A batch that fits must never report omissions.
        assert "records_omitted:" not in body


def test_batches_carry_part_numbers():
    """The reader needs to know whether it has the whole set."""
    body = EmailDelivery.format_report_email(
        new_count=1, changed_count=0, expired_count=0, failed_sources=0,
        jobs=[make_job(1)], total_active=100, part=3, total_parts=7,
    )

    assert "part: 3 of 7" in body


def test_smaller_descriptions_yield_fewer_batches():
    """Lowering the cap is the lever for fitting more jobs per message."""
    jobs = [make_job(i, desc_chars=800) for i in range(200)]
    at_800 = len(EmailDelivery.split_into_batches(jobs))

    original = EmailDelivery.MAX_DESCRIPTION_CHARS
    try:
        EmailDelivery.MAX_DESCRIPTION_CHARS = 200
        at_200 = len(EmailDelivery.split_into_batches(jobs))
    finally:
        EmailDelivery.MAX_DESCRIPTION_CHARS = original

    assert at_200 < at_800


def test_single_job_never_produces_an_empty_batch():
    assert EmailDelivery.split_into_batches([make_job(1, desc_chars=500_000)]) != []


def test_no_jobs_produces_no_batches():
    assert EmailDelivery.split_into_batches([]) == []
