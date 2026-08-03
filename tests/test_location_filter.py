"""Tests for location filtering."""
import pytest

from job_collector.config import LocationFilter
from job_collector.collectors.workday import WorkdayCollector


AUSTIN_AREA = ["Austin", "Buda", "Round Rock", "Georgetown", "Texas", ", TX", "Remote"]
COUNTRIES = ["Germany", "Hungary", "India", "United Kingdom", "Mexico", "Japan"]


def test_disabled_filter_keeps_everything():
    """A disabled filter must not drop anything."""
    location_filter = LocationFilter(enabled=False, include=AUSTIN_AREA)

    assert location_filter.matches("Bangalore, India")
    assert location_filter.matches("Malaysia, Penang")


def test_empty_include_keeps_everything():
    """An enabled filter with no patterns must not silently drop everything."""
    location_filter = LocationFilter(enabled=True, include=[])

    assert location_filter.matches("Bangalore, India")


@pytest.mark.parametrize(
    "location",
    [
        "Austin, TX",
        "AUSTIN, TX",
        "AUSTIN TX",  # recovered from a path slug
        "Round Rock Campus",
        "Austin Energy",
        "Remote, USA",
        "US, Texas, Austin",
    ],
)
def test_keeps_in_area_locations(location):
    """In-area and remote postings are kept."""
    assert LocationFilter(enabled=True, include=AUSTIN_AREA).matches(location)


@pytest.mark.parametrize(
    "location",
    ["Bangalore, India", "Malaysia, Penang", "Noida", "San Jose", "Toulouse", "Catania"],
)
def test_drops_out_of_area_locations(location):
    """Out-of-area postings are dropped."""
    assert not LocationFilter(enabled=True, include=AUSTIN_AREA).matches(location)


def test_missing_location_is_dropped():
    """A job with no location cannot be confirmed in-area."""
    assert not LocationFilter(enabled=True, include=AUSTIN_AREA).matches("")


def test_include_matches_on_word_boundaries():
    """"Buda" (a Texas suburb) must not match "Budapest"."""
    location_filter = LocationFilter(enabled=True, include=AUSTIN_AREA)

    assert location_filter.matches("Buda, TX")
    assert not location_filter.matches("Budapest, Hungary")


@pytest.mark.parametrize(
    "location",
    [
        "Remote (Germany)",
        "Remote, Mexico",
        "Remote (United Kingdom)",
        "Remote (Japan)",
        "Bangalore, India",
    ],
)
def test_exclude_beats_include(location):
    """Bare "Remote" must not smuggle in international postings."""
    location_filter = LocationFilter(enabled=True, include=AUSTIN_AREA, exclude=COUNTRIES)

    assert not location_filter.matches(location)


@pytest.mark.parametrize(
    "location",
    ["Remote California", "Remote, North Carolina, USA", "Remote Texas", "Austin, TX"],
)
def test_exclude_keeps_domestic_remote(location):
    """US remote roles survive the exclusions."""
    location_filter = LocationFilter(enabled=True, include=AUSTIN_AREA, exclude=COUNTRIES)

    assert location_filter.matches(location)


def make_collector() -> WorkdayCollector:
    from job_collector.config import SourceConfig

    return WorkdayCollector(
        "nxp",
        SourceConfig(type="workday", tenant="nxp", wd_host="wd3", site="careers"),
    )


@pytest.mark.parametrize(
    "locations_text,external_path,expected",
    [
        # Workday hides the location behind "N Locations"; recover it from the path.
        ("2 Locations", "/job/Noida/Embedded-Engineer_R-1", "Noida"),
        ("3 Locations", "/job/AUSTIN-TX/Analyst_R-2", "AUSTIN TX"),
        ("2 locations", "/job/Austin-Energy/Electrician_R-3", "Austin Energy"),
        # A real location is left alone.
        ("Austin, TX", "/job/AUSTIN-TX/Analyst_R-4", "Austin, TX"),
    ],
)
def test_multi_location_recovered_from_path(locations_text, external_path, expected):
    """'2 Locations' carries no information, so fall back to the path slug."""
    collector = make_collector()
    summary = {
        "title": "Role",
        "externalPath": external_path,
        "locationsText": locations_text,
        "bulletFields": [],
    }

    assert collector._parse_job(summary, None).location == expected


def test_location_falls_back_to_unknown():
    """An unparseable path must not crash or produce an empty location."""
    collector = make_collector()
    summary = {"title": "Role", "externalPath": "", "locationsText": "", "bulletFields": []}

    assert collector._parse_job(summary, None).location == "Unknown"
