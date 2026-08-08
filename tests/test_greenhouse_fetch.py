"""Tests for Greenhouse fetching, which must not loop on a non-paginating API."""
import httpx
import pytest

from job_collector.collectors.greenhouse import GreenhouseCollector
from job_collector.config import SourceConfig


def board(n_jobs: int):
    """A board response containing n_jobs postings."""
    return {
        "jobs": [
            {
                "id": 1000 + i,
                "title": f"Engineer {i}",
                "absolute_url": f"https://example.com/jobs/{1000 + i}",
                "offices": [{"name": "Austin, TX"}],
                "departments": [],
                "content": "<p>Work</p>",
            }
            for i in range(n_jobs)
        ]
    }


def collector_with(handler):
    cfg = SourceConfig(type="greenhouse", board_token="natera")
    return GreenhouseCollector("natera", cfg), httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_fetches_full_board_in_one_request():
    """The API returns the whole board at once; one request is enough."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=board(225))

    c, client = collector_with(handler)
    async with client:
        jobs = await c._fetch_jobs(client)

    assert len(jobs) == 225
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_does_not_loop_when_api_ignores_pagination():
    """Regression: a full page every time previously looped forever.

    Greenhouse ignores page/per_page and always returns the entire board, so a
    loop that stops only on a short page never terminates.
    """
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] > 5:
            raise AssertionError("collector paginated against a non-paginating API")
        return httpx.Response(200, json=board(225))

    c, client = collector_with(handler)
    async with client:
        jobs = await c._fetch_jobs(client)

    assert len(jobs) == 225
    assert calls["n"] == 1


def parse_one(job_data: dict):
    from job_collector.collectors.greenhouse import GreenhouseCollector
    from job_collector.config import SourceConfig
    return GreenhouseCollector("acme", SourceConfig(type="greenhouse", board_token="acme"))._parse_job(job_data)


def test_location_comes_from_the_posting_not_the_office_name():
    """`offices[].name` is the office's name, not a place.

    Tecovas and AlertMedia name their offices "Tecovas HQ" / "AlertMedia HQ",
    so using that as the location made every posting look out-of-area.
    """
    job = parse_one({
        "id": 1,
        "title": "Assistant Merchant",
        "absolute_url": "https://example.com/1",
        "location": {"name": "Austin, TX"},
        "offices": [{"name": "Tecovas HQ", "location": "801 Barton Springs Rd. Austin, TX 78704"}],
    })

    assert job.location == "Austin, TX"


def test_falls_back_to_office_address_then_name():
    """Without a posting location, an address beats an office nickname."""
    with_address = parse_one({
        "id": 2, "title": "Role", "absolute_url": "https://example.com/2",
        "offices": [{"name": "AlertMedia HQ", "location": "Austin, Texas, United States"}],
    })
    name_only = parse_one({
        "id": 3, "title": "Role", "absolute_url": "https://example.com/3",
        "offices": [{"name": "San Francisco, CA"}],
    })

    assert with_address.location == "Austin, Texas, United States"
    assert name_only.location == "San Francisco, CA"


def test_no_location_information_falls_back_to_remote():
    job = parse_one({"id": 4, "title": "Role", "absolute_url": "https://example.com/4"})

    assert job.location == "Remote"


@pytest.mark.asyncio
async def test_empty_board_returns_no_jobs():
    """An empty board is not an error."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": []})

    c, client = collector_with(handler)
    async with client:
        assert await c._fetch_jobs(client) == []


@pytest.mark.asyncio
async def test_missing_jobs_key_is_tolerated():
    """A malformed payload should yield nothing rather than raise."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    c, client = collector_with(handler)
    async with client:
        assert await c._fetch_jobs(client) == []
