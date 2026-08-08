"""Tests for the machine-readable email body.

The body is consumed by an automated reader, so it must be self-contained and
parseable: attachments arrive as application/octet-stream and cannot be opened.
"""
from datetime import datetime

import pytest

from job_collector.email_delivery import EmailDelivery
from job_collector.models import EmploymentType, JobStatus, NormalizedJob, RemoteStatus


def make_job(**kwargs) -> NormalizedJob:
    defaults = dict(
        source_type="workday",
        source_company_id="q2-holdings",
        source_job_id="REQ-12676",
        company_name="Q2 Holdings",
        title="Software Engineer in Test",
        location="Austin, TX",
        apply_url="https://q2ebanking.wd5.myworkdayjobs.com/Q2/job/Austin-TX/SEIT_REQ-12676",
        source_url="https://example.com/1",
        description_text="Build and maintain automated test suites.",
        employment_type=EmploymentType.FULL_TIME,
        remote_status=RemoteStatus.UNKNOWN,
        date_posted=datetime(2026, 7, 28),
        status=JobStatus.NEW,
    )
    defaults.update(kwargs)
    return NormalizedJob(**defaults)


def parse_records(body: str) -> list[dict]:
    """Parse the body the way a downstream consumer would."""
    records, current, in_desc = [], None, False
    for line in body.splitlines():
        if line == "JOB":
            current, in_desc = {"description": []}, False
            continue
        if line == "END JOB":
            current["description"] = "\n".join(current["description"]).strip()
            records.append(current)
            current, in_desc = None, False
            continue
        if current is None:
            continue
        if in_desc:
            current["description"].append(line)
        elif line == "description:":
            in_desc = True
        elif ": " in line or line.endswith(":"):
            key, _, value = line.partition(":")
            current[key.strip()] = value.strip()
    return records


def test_header_reports_all_four_counts():
    """Totals must be distinguishable: active vs new vs changed vs expired."""
    body = EmailDelivery.format_report_email(
        new_count=17, changed_count=2, expired_count=9, failed_sources=0,
        jobs=[make_job()], total_active=1373,
    )

    assert "total_active: 1373" in body
    assert "new: 17" in body
    assert "changed: 2" in body
    assert "expired: 9" in body
    assert "records_included: 1" in body


def test_record_round_trips_every_required_field():
    """Each field the consumer asked for survives formatting."""
    body = EmailDelivery.format_report_email(
        new_count=1, changed_count=0, expired_count=0, failed_sources=0,
        jobs=[make_job()], total_active=1,
    )
    [record] = parse_records(body)

    assert record["id"] == "q2-holdings#workday|REQ-12676"
    assert record["company"] == "Q2 Holdings"
    assert record["title"] == "Software Engineer in Test"
    assert record["location"] == "Austin, TX"
    assert record["employment_type"] == "full_time"
    assert record["remote"] == "unknown"
    assert record["status"] == "new"
    assert record["posted_date"] == "2026-07-28"
    assert record["source"] == "q2-holdings#workday"
    assert record["apply_url"].endswith("SEIT_REQ-12676")
    assert "automated test suites" in record["description"]


def test_multiple_records_parse_independently():
    """A 400-job body must split cleanly into records."""
    jobs = [make_job(source_job_id=f"REQ-{i}", title=f"Role {i}") for i in range(25)]
    body = EmailDelivery.format_report_email(
        new_count=25, changed_count=0, expired_count=0, failed_sources=0,
        jobs=jobs, total_active=25,
    )
    records = parse_records(body)

    assert len(records) == 25
    assert {r["title"] for r in records} == {f"Role {i}" for i in range(25)}


def test_multiline_description_is_preserved():
    """Descriptions span lines; the terminator still ends the record."""
    job = make_job(description_text="First paragraph.\n\nSecond paragraph.\n- bullet")
    body = EmailDelivery.format_report_email(
        new_count=1, changed_count=0, expired_count=0, failed_sources=0,
        jobs=[job], total_active=1,
    )
    [record] = parse_records(body)

    assert "First paragraph." in record["description"]
    assert "Second paragraph." in record["description"]
    assert "- bullet" in record["description"]


def test_description_cannot_break_out_of_its_record():
    """A description containing the terminator must not split the record."""
    job = make_job(description_text="Responsibilities\nEND JOB\nid: injected")
    body = EmailDelivery.format_report_email(
        new_count=1, changed_count=0, expired_count=0, failed_sources=0,
        jobs=[job], total_active=1,
    )
    records = parse_records(body)

    assert len(records) == 1
    assert records[0]["id"] == "q2-holdings#workday|REQ-12676"


def test_newlines_in_scalar_fields_are_flattened():
    """A stray newline in a title would otherwise corrupt the next field."""
    job = make_job(title="Technician II\nNight Shift")
    body = EmailDelivery.format_report_email(
        new_count=1, changed_count=0, expired_count=0, failed_sources=0,
        jobs=[job], total_active=1,
    )
    [record] = parse_records(body)

    assert record["title"] == "Technician II Night Shift"


def test_long_description_is_truncated_but_marked():
    """Very long descriptions are capped, and say so."""
    job = make_job(description_text="x" * 9000)
    body = EmailDelivery.format_report_email(
        new_count=1, changed_count=0, expired_count=0, failed_sources=0,
        jobs=[job], total_active=1,
    )
    [record] = parse_records(body)

    assert "[truncated]" in record["description"]
    assert len(record["description"]) < 9000


def test_cap_is_reported_not_silent():
    """Omitting records must be stated, so a capped run is not read as quiet."""
    jobs = [make_job(source_job_id=f"R{i}") for i in range(10)]
    body = EmailDelivery.format_report_email(
        new_count=10, changed_count=0, expired_count=0, failed_sources=0,
        jobs=jobs, total_active=10, max_jobs=4,
    )

    assert "records_included: 4" in body
    assert "records_omitted: 6" in body
    assert len(parse_records(body)) == 4


def test_body_stays_under_the_size_budget():
    """A clipped body would hide records, so the budget is enforced here."""
    jobs = [make_job(source_job_id=f"R{i}", description_text="x" * 1800) for i in range(200)]
    body = EmailDelivery.format_report_email(
        new_count=200, changed_count=0, expired_count=0, failed_sources=0,
        jobs=jobs, total_active=200,
    )

    assert len(body.encode("utf-8")) <= EmailDelivery.MAX_BODY_BYTES
    assert "records_omitted:" in body
    assert "body size limit" in body
    # Whatever survived must still parse cleanly.
    assert len(parse_records(body)) == int(
        [l for l in body.splitlines() if l.startswith("records_included:")][0].split(": ")[1]
    )


def test_single_oversized_job_is_still_sent():
    """One job larger than the budget should not produce an empty report."""
    body = EmailDelivery.format_report_email(
        new_count=1, changed_count=0, expired_count=0, failed_sources=0,
        jobs=[make_job(description_text="x" * 50000)], total_active=1, max_bytes=500,
    )

    assert len(parse_records(body)) == 1


def test_typical_daily_volume_fits_comfortably():
    """A normal day (about 20 changed jobs) must not be truncated at all."""
    jobs = [make_job(source_job_id=f"R{i}", description_text="y" * 1500) for i in range(20)]
    body = EmailDelivery.format_report_email(
        new_count=20, changed_count=0, expired_count=0, failed_sources=0,
        jobs=jobs, total_active=1375,
    )

    assert "records_omitted:" not in body
    assert len(parse_records(body)) == 20


def test_missing_optional_fields_still_emit_keys():
    """Absent values yield empty strings rather than dropped keys."""
    job = make_job(date_posted=None, salary_text="")
    body = EmailDelivery.format_report_email(
        new_count=1, changed_count=0, expired_count=0, failed_sources=0,
        jobs=[job], total_active=1,
    )
    [record] = parse_records(body)

    assert record["posted_date"] == ""
    assert record["salary"] == ""
    assert record["first_seen"]
