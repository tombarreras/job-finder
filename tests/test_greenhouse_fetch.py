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
