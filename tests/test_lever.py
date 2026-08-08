"""Tests for the Lever collector.

Payloads mirror the real public API (api.lever.co/v0/postings/{board}?mode=json),
which returns a flat list of postings with location, department, team and
commitment nested under "categories" as plain strings. The previous fixtures
described a shape Lever does not emit, which is why the collector passed its
tests while failing against every real board.
"""
import httpx
import pytest

from job_collector.collectors.lever import LeverCollector
from job_collector.config import SourceConfig
from job_collector.models import EmploymentType, RemoteStatus


def make_collector() -> LeverCollector:
    return LeverCollector("arrivelogistics", SourceConfig(type="lever", board_name="arrivelogistics"))


def real_posting(**overrides) -> dict:
    posting = {
        "id": "16608370-2d00-4397-9ff6-ffae861ba067",
        "text": "Accounts Receivable Specialist",
        "categories": {
            "commitment": "Full-time",
            "department": "Finance",
            "location": "Austin, TX",
            "team": "Carrier and Customer Relations",
            "allLocations": ["Austin, TX"],
        },
        "createdAt": "1677884732296",
        "hostedUrl": "https://jobs.lever.co/arrivelogistics/16608370",
        "applyUrl": "https://jobs.lever.co/arrivelogistics/16608370/apply",
        "descriptionPlain": "Own the accounts receivable process.",
        "additionalPlain": "Requirements: 2 years experience.",
        "workplaceType": "onsite",
        "country": "US",
    }
    posting.update(overrides)
    return posting


def test_parses_a_real_posting():
    job = make_collector()._parse_job(real_posting())

    assert job.source_type == "lever"
    assert job.source_job_id == "16608370-2d00-4397-9ff6-ffae861ba067"
    assert job.title == "Accounts Receivable Specialist"
    assert job.location == "Austin, TX"
    assert job.department == "Finance"
    assert job.team == "Carrier and Customer Relations"
    assert job.employment_type == EmploymentType.FULL_TIME
    assert job.remote_status == RemoteStatus.ON_SITE
    assert job.apply_url.endswith("/apply")
    assert job.content_hash


def test_description_includes_the_additional_section():
    """Requirements and benefits live in additionalPlain, not description."""
    job = make_collector()._parse_job(real_posting())

    assert "accounts receivable process" in job.description_text
    assert "2 years experience" in job.description_text


@pytest.mark.parametrize(
    "commitment,expected",
    [
        ("Full-time", EmploymentType.FULL_TIME),
        ("Part-time", EmploymentType.PART_TIME),
        ("Contract", EmploymentType.CONTRACT),
        ("Internship", EmploymentType.APPRENTICESHIP),
        ("", EmploymentType.UNKNOWN),
    ],
)
def test_employment_type_comes_from_commitment(commitment, expected):
    """Employment type is categories.commitment, not workplaceType."""
    posting = real_posting()
    posting["categories"]["commitment"] = commitment

    assert make_collector()._parse_job(posting).employment_type == expected


@pytest.mark.parametrize(
    "workplace,expected",
    [
        ("onsite", RemoteStatus.ON_SITE),
        ("hybrid", RemoteStatus.HYBRID),
        ("remote", RemoteStatus.REMOTE),
        ("", RemoteStatus.UNKNOWN),
    ],
)
def test_remote_status_from_workplace_type(workplace, expected):
    assert make_collector()._parse_job(
        real_posting(workplaceType=workplace)
    ).remote_status == expected


def test_created_at_is_parsed_as_utc_from_a_string():
    """Lever sends epoch milliseconds, sometimes as a string."""
    job = make_collector()._parse_job(real_posting(createdAt="1677884732296"))

    assert job.date_posted is not None
    assert (job.date_posted.year, job.date_posted.month, job.date_posted.day) == (2023, 3, 3)


def test_falls_back_to_all_locations_then_remote():
    posting = real_posting()
    posting["categories"] = {"allLocations": ["Austin, TX", "Dallas, TX"]}
    assert "Dallas" in make_collector()._parse_job(posting).location

    posting["categories"] = {}
    assert make_collector()._parse_job(posting).location == "Remote"


def test_falls_back_to_hosted_url_when_apply_url_missing():
    job = make_collector()._parse_job(real_posting(applyUrl=""))

    assert job.apply_url == "https://jobs.lever.co/arrivelogistics/16608370"


@pytest.mark.asyncio
async def test_fetch_handles_the_flat_list_response():
    """The API returns a list; calling .get() on it used to raise."""
    postings = [real_posting(id=f"id-{i}") for i in range(3)]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=postings)

    collector = make_collector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await collector._fetch_jobs(client)

    assert len(jobs) == 3
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_unexpected_payload_shape_returns_nothing():
    """A dict response should be reported, not crash the source."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    collector = make_collector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await collector._fetch_jobs(client) == []
