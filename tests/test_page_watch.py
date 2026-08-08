"""Tests for watching apprenticeship pages.

These pages publish application *windows*, not job postings, so a change is the
signal. The risks are the opposite of a scraper's: false positives from
rotating page furniture, and silent failure when a URL quietly rots.
"""
import httpx
import pytest

from job_collector.database import JobDatabase
from job_collector.page_watch import (
    PageWatcher,
    WatchConfig,
    added_lines,
    extract_text,
    load_watches,
)


@pytest.fixture
def db(tmp_path):
    return JobDatabase(tmp_path / "watch.db")


def watcher_for(db, pages):
    """A watcher whose transport serves successive bodies from `pages`."""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = pages[min(state["n"], len(pages) - 1)]
        state["n"] += 1
        if isinstance(body, int):
            return httpx.Response(body, text="error")
        return httpx.Response(200, text=body)

    return PageWatcher(db), httpx.MockTransport(handler), state


async def check(db, pages, watch=None, times=1):
    watch = watch or WatchConfig(
        id="eta", name="Austin ETA", url="https://austineta.org/apprentice-program-2/",
        keywords=["accepting applications", "deadline"],
    )
    w, transport, _ = watcher_for(db, pages)
    results = []
    async with httpx.AsyncClient(transport=transport) as client:
        for _ in range(times):
            results.append(await w._check(client, watch))
    return results


def test_extract_text_drops_scripts_and_styles():
    """Script nonces change every load and would fake a change every check."""
    html = """<html><head><style>.a{color:red}</style>
        <script>var nonce='abc123';</script></head>
        <body><h1>Apprentice Program</h1><p>Applications closed.</p></body></html>"""

    text = extract_text(html)

    assert "Apprentice Program" in text
    assert "Applications closed." in text
    assert "nonce" not in text
    assert "color:red" not in text


def test_added_lines_reports_only_new_text():
    before = "Apprentice Program\nApplications closed."
    after = "Apprentice Program\nApplications closed.\nNow accepting applications for 2027."

    assert added_lines(before, after) == "Now accepting applications for 2027."


@pytest.mark.asyncio
async def test_first_check_records_a_baseline(db):
    [result] = await check(db, ["<p>Applications closed.</p>"])

    assert result.status == "new"
    assert result.added_text == ""


@pytest.mark.asyncio
async def test_identical_page_is_unchanged(db):
    results = await check(db, ["<p>Applications closed for this cycle.</p>"], times=2)

    assert [r.status for r in results] == ["new", "unchanged"]


@pytest.mark.asyncio
async def test_meaningful_change_is_reported_with_keywords(db):
    results = await check(db, [
        "<p>Applications closed for this cycle.</p>",
        "<p>Applications closed for this cycle.</p>"
        "<p>We are now accepting applications. The deadline is 1 October.</p>",
    ], times=2)

    change = results[1]
    assert change.status == "changed"
    assert "now accepting applications" in change.added_text.lower()
    assert "deadline" in change.keywords_found


@pytest.mark.asyncio
async def test_trivial_change_is_not_reported(db):
    """Rotating furniture must not cry wolf every morning."""
    results = await check(db, [
        "<p>Applications closed for this cycle.</p><span>Visitors: 1041</span>",
        "<p>Applications closed for this cycle.</p><span>Visitors: 1042</span>",
    ], times=2)

    assert results[1].status == "unchanged"


@pytest.mark.asyncio
async def test_trivial_change_does_not_retrigger(db):
    """The new text is stored even when unreported, so it settles."""
    results = await check(db, [
        "<p>Applications closed.</p><span>1041</span>",
        "<p>Applications closed.</p><span>1042</span>",
        "<p>Applications closed.</p><span>1042</span>",
    ], times=3)

    assert [r.status for r in results] == ["new", "unchanged", "unchanged"]


@pytest.mark.asyncio
async def test_soft_404_is_an_error_not_a_baseline(db):
    """centexiec.com serves its 404 body with HTTP 200.

    Treating that as a valid baseline would leave the watch silently pointed at
    an error page.
    """
    [result] = await check(db, ["<h1>404 Page</h1><p>Nothing here.</p>"])

    assert result.status == "error"
    assert "404" in result.error


@pytest.mark.asyncio
async def test_http_error_is_reported(db):
    [result] = await check(db, [503])

    assert result.status == "error"
    assert result.error


def test_load_watches_reads_the_real_config(tmp_path):
    (tmp_path / "watches.yaml").write_text(
        "watches:\n"
        "  - id: a\n    name: A\n    url: https://example.com/a\n"
        "    keywords: [apply]\n"
        "  - id: b\n    name: B\n    url: https://example.com/b\n    enabled: false\n",
        encoding="utf-8",
    )

    watches = load_watches(tmp_path)

    assert [w.id for w in watches] == ["a"]
    assert watches[0].keywords == ["apply"]


def test_missing_config_is_not_an_error(tmp_path):
    assert load_watches(tmp_path) == []
