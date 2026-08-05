"""Tests for Workday transient-failure retries."""
import httpx
import pytest

from job_collector.collectors import workday as workday_module
from job_collector.collectors.workday import WorkdayCollector
from job_collector.config import SourceConfig


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Make backoff instant so tests stay fast."""
    async def instant(_seconds):
        return None

    monkeypatch.setattr(workday_module.asyncio, "sleep", instant)


def make_collector(**parsing) -> WorkdayCollector:
    return WorkdayCollector(
        "intel",
        SourceConfig(
            type="workday", tenant="intel", wd_host="wd1", site="External",
            parsing_config=parsing,
        ),
    )


def client_for(responses):
    """Build a client whose transport replays the given status codes."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        index = min(calls["n"], len(responses) - 1)
        status, body, headers = responses[index]
        calls["n"] += 1
        return httpx.Response(status, json=body, headers=headers)

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport), calls


EMPTY = {"total": 0, "jobPostings": []}


@pytest.mark.asyncio
async def test_retries_429_then_succeeds():
    """A throttled request is retried rather than aborting the source."""
    collector = make_collector()
    client, calls = client_for([(429, {}, {}), (429, {}, {}), (200, EMPTY, {})])

    async with client:
        response = await collector._request(client, "POST", "https://example.test/jobs", json={})

    assert response.status_code == 200
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts():
    """Persistent throttling still surfaces as an error."""
    collector = make_collector()
    client, calls = client_for([(429, {}, {})])

    async with client:
        with pytest.raises(httpx.HTTPStatusError):
            await collector._request(client, "POST", "https://example.test/jobs", json={})

    assert calls["n"] == workday_module.MAX_ATTEMPTS


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_retries_server_errors(status):
    """5xx responses are transient and worth retrying."""
    collector = make_collector()
    client, calls = client_for([(status, {}, {}), (200, EMPTY, {})])

    async with client:
        response = await collector._request(client, "GET", "https://example.test/job/1")

    assert response.status_code == 200
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_does_not_retry_client_errors():
    """404/422 mean a wrong site id, so retrying just wastes time."""
    collector = make_collector()
    client, calls = client_for([(422, {}, {})])

    async with client:
        with pytest.raises(httpx.HTTPStatusError):
            await collector._request(client, "POST", "https://example.test/jobs", json={})

    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_honours_retry_after_header(monkeypatch):
    """A numeric Retry-After overrides the computed backoff."""
    collector = make_collector()
    slept: list[float] = []

    async def record(seconds):
        slept.append(seconds)

    monkeypatch.setattr(workday_module.asyncio, "sleep", record)
    client, _ = client_for([(429, {}, {"Retry-After": "7"}), (200, EMPTY, {})])

    async with client:
        await collector._request(client, "POST", "https://example.test/jobs", json={})

    # Jitter adds up to 25%, so check the band rather than an exact value.
    assert slept and 7.0 <= slept[0] <= 7.0 * 1.25


@pytest.mark.asyncio
async def test_search_survives_a_throttled_page():
    """A 429 during pagination must not lose the whole source."""
    collector = make_collector()
    page = {
        "total": 1,
        "jobPostings": [
            {"title": "Engineer", "externalPath": "/job/Austin/Engineer_R-1", "bulletFields": []}
        ],
    }
    client, _ = client_for([(429, {}, {}), (200, page, {})])

    async with client:
        found = await collector._search(client, "", max_jobs=100, warnings=[])

    assert len(found) == 1
    assert found[0]["title"] == "Engineer"
