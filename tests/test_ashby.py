"""Tests for the Ashby collector.

Payloads mirror the real public API
(api.ashbyhq.com/posting-api/job-board/{org}), where location, department and
team are plain strings and employmentType/workplaceType are CamelCase. The
previous fixtures described a city/state/country dict Ashby does not emit, and
pointed at api.ashby.io, a host that does not resolve.
"""
import httpx
import pytest

from job_collector.collectors.ashby import AshbyCollector
from job_collector.config import SourceConfig
from job_collector.models import EmploymentType, RemoteStatus


def make_collector() -> AshbyCollector:
    return AshbyCollector("zello", SourceConfig(type="ashby", board_name="zello"))


def real_posting(**overrides) -> dict:
    posting = {
        "id": "3f58eb10-2752-493f-909f-19a9e82b1744",
        "title": "Senior RevOps Analyst",
        "location": "Austin, Texas",
        "secondaryLocations": [],
        "department": "RevOps",
        "team": "RevOps",
        "employmentType": "FullTime",
        "publishedAt": "2026-07-28T22:42:44.683+00:00",
        "jobUrl": "https://jobs.ashbyhq.com/zello/3f58eb10",
        "applyUrl": "https://jobs.ashbyhq.com/zello/3f58eb10/application",
        "descriptionPlain": "Own revenue operations reporting.",
        "descriptionHtml": "<p>Own revenue operations reporting.</p>",
        "isRemote": False,
        "isListed": True,
        "workplaceType": "Hybrid",
    }
    posting.update(overrides)
    return posting


def test_parses_a_real_posting():
    job = make_collector()._parse_job(real_posting())

    assert job.source_type == "ashby"
    assert job.source_job_id == "3f58eb10-2752-493f-909f-19a9e82b1744"
    assert job.title == "Senior RevOps Analyst"
    assert job.location == "Austin, Texas"
    assert job.department == "RevOps"
    assert job.team == "RevOps"
    assert job.employment_type == EmploymentType.FULL_TIME
    assert job.remote_status == RemoteStatus.HYBRID
    assert job.description_text == "Own revenue operations reporting."
    assert job.apply_url.endswith("/application")
    assert job.content_hash


@pytest.mark.parametrize(
    "value,expected",
    [
        ("FullTime", EmploymentType.FULL_TIME),
        ("PartTime", EmploymentType.PART_TIME),
        ("Contract", EmploymentType.CONTRACT),
        ("Temporary", EmploymentType.TEMPORARY),
        ("Intern", EmploymentType.APPRENTICESHIP),
        ("", EmploymentType.UNKNOWN),
    ],
)
def test_camelcase_employment_types(value, expected):
    assert make_collector()._parse_job(
        real_posting(employmentType=value)
    ).employment_type == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Remote", RemoteStatus.REMOTE),
        ("Hybrid", RemoteStatus.HYBRID),
        ("OnSite", RemoteStatus.ON_SITE),
        ("", RemoteStatus.UNKNOWN),
    ],
)
def test_camelcase_workplace_types(value, expected):
    assert make_collector()._parse_job(
        real_posting(workplaceType=value)
    ).remote_status == expected


def test_is_remote_flag_is_used_when_workplace_type_absent():
    job = make_collector()._parse_job(real_posting(workplaceType="", isRemote=True))

    assert job.remote_status == RemoteStatus.REMOTE


def test_secondary_locations_are_appended():
    job = make_collector()._parse_job(
        real_posting(secondaryLocations=[{"location": "Dallas, Texas"}])
    )

    assert "Austin, Texas" in job.location
    assert "Dallas, Texas" in job.location


def test_published_at_is_parsed():
    job = make_collector()._parse_job(real_posting())

    assert job.date_posted is not None
    assert (job.date_posted.year, job.date_posted.month, job.date_posted.day) == (2026, 7, 28)


def test_missing_location_falls_back_to_remote():
    assert make_collector()._parse_job(
        real_posting(location="", secondaryLocations=[])
    ).location == "Remote"


def test_compensation_summary_is_used_when_present():
    job = make_collector()._parse_job(
        real_posting(compensation={"compensationTierSummary": "$120K – $150K"})
    )

    assert job.salary_text == "$120K – $150K"


def test_empty_compensation_object_yields_no_salary():
    """The API usually returns an object whose tiers are all empty."""
    job = make_collector()._parse_job(
        real_posting(compensation={"compensationTierSummary": None, "compensationTiers": []})
    )

    assert job.salary_text == ""


@pytest.mark.asyncio
async def test_fetch_uses_a_single_get_and_skips_unlisted():
    postings = {
        "apiVersion": "1",
        "jobs": [
            real_posting(id="a"),
            real_posting(id="b", isListed=False),
            real_posting(id="c"),
        ],
    }
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(200, json=postings)

    collector = make_collector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await collector._fetch_jobs(client)

    assert seen["method"] == "GET"
    assert "api.ashbyhq.com/posting-api/job-board/zello" in seen["url"]
    assert [j.source_job_id for j in jobs] == ["a", "c"]


@pytest.mark.asyncio
async def test_empty_board_returns_no_jobs():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"apiVersion": "1", "jobs": []})

    collector = make_collector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await collector._fetch_jobs(client) == []
