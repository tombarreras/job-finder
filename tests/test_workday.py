"""Tests for Workday collector."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from job_collector.collectors.workday import WorkdayCollector
from job_collector.config import SourceConfig
from job_collector.models import EmploymentType, RemoteStatus


@pytest.fixture
def workday_fixture():
    """Load Workday API response fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "workday_response.json"
    with open(fixture_path) as f:
        return json.load(f)


def make_collector(**kwargs) -> WorkdayCollector:
    """Build a collector with sensible Workday coordinates."""
    defaults = {"type": "workday", "tenant": "austintexas", "wd_host": "wd5", "site": "COA_Careers"}
    defaults.update(kwargs)
    return WorkdayCollector("city-of-austin", SourceConfig(**defaults))


def test_resolves_explicit_coordinates():
    """Should use tenant/wd_host/site when given explicitly."""
    collector = make_collector()

    assert collector.tenant == "austintexas"
    assert collector.wd_host == "wd5"
    assert collector.site == "COA_Careers"
    assert collector.api_url == (
        "https://austintexas.wd5.myworkdayjobs.com/wday/cxs/austintexas/COA_Careers"
    )


def test_derives_coordinates_from_site_url():
    """Should parse tenant/host/site out of a public careers URL."""
    source_config = SourceConfig(
        type="workday",
        site_url="https://utaustin.wd1.myworkdayjobs.com/UTstaff",
    )
    collector = WorkdayCollector("ut-austin", source_config)

    assert collector.tenant == "utaustin"
    assert collector.wd_host == "wd1"
    assert collector.site == "UTstaff"


def test_derives_coordinates_from_localized_site_url():
    """Should tolerate the /en-US/ locale segment Workday sometimes emits."""
    source_config = SourceConfig(
        type="workday",
        site_url="https://nxp.wd3.myworkdayjobs.com/en-US/careers",
    )
    collector = WorkdayCollector("nxp", source_config)

    assert collector.tenant == "nxp"
    assert collector.wd_host == "wd3"
    assert collector.site == "careers"


@pytest.mark.asyncio
async def test_collect_without_coordinates_errors():
    """Should fail cleanly when tenant/site cannot be resolved."""
    collector = WorkdayCollector("mystery-co", SourceConfig(type="workday"))

    result = await collector.collect()

    assert result.jobs == []
    assert result.complete is False
    assert "Missing Workday coordinates" in result.errors[0]


def test_parse_job_from_summary_and_detail(workday_fixture):
    """Should merge summary and detail into a normalized job."""
    collector = make_collector()
    summary = workday_fixture["search"]["jobPostings"][1]
    detail = workday_fixture["detail"]["jobPostingInfo"]

    job = collector._parse_job(summary, detail)

    assert job.source_type == "workday"
    assert job.source_company_id == "city-of-austin"
    assert job.source_job_id == "JR104610"
    assert job.title == "Electrician Helper"
    assert job.location == "Austin Energy"
    assert "Assist licensed electricians" in job.description_text
    assert "<p>" not in job.description_text
    assert job.apply_url == detail["externalUrl"]
    assert job.employment_type == EmploymentType.FULL_TIME
    assert job.content_hash


def test_parse_job_summary_only(workday_fixture):
    """Should parse without a detail record, building the apply URL from the path."""
    collector = make_collector()
    summary = workday_fixture["search"]["jobPostings"][0]

    job = collector._parse_job(summary, None)

    assert job.source_job_id == "JR104602"
    assert job.title == "Customer Service Representative (Automotive)"
    assert job.location == "Austin Fleet Mobility Services"
    assert job.description_text == ""
    assert job.apply_url == (
        "https://austintexas.wd5.myworkdayjobs.com/COA_Careers"
        "/job/Austin-Fleet-Mobility-Services"
        "/Customer-Service-Representative--Automotive-_JR104602"
    )


def test_parse_job_falls_back_to_external_path_for_id():
    """Should use the path as job id when no requisition id can be found."""
    collector = make_collector()
    summary = {"title": "Analyst", "externalPath": "/job/Austin/Analyst", "bulletFields": []}

    job = collector._parse_job(summary, None)

    assert job.source_job_id == "/job/Austin/Analyst"


@pytest.mark.parametrize(
    "external_path,expected",
    [
        ("/job/Austin-Energy/Electrician-Helper_JR104610", "JR104610"),
        ("/job/Catania/Senior-Principal-HW-SW-Co-Design-Lead_R-10065705", "R-10065705"),
    ],
)
def test_job_id_extracted_from_external_path(external_path, expected):
    """Should recover the requisition id from the path when detail is absent."""
    collector = make_collector()
    summary = {"title": "Role", "externalPath": external_path, "bulletFields": []}

    assert collector._parse_job(summary, None).source_job_id == expected


def test_ignores_non_requisition_bullet_fields():
    """Should not collapse distinct postings that share a bulletFields label.

    Intel labels promoted postings "Spotlight Job" in bulletFields; trusting it
    would map every such posting onto a single id.
    """
    collector = make_collector()
    first = {
        "title": "Atom CPU Layout Design Engineer",
        "externalPath": "/job/Austin/Atom-CPU-Layout-Design-Engineer_JR0270001",
        "bulletFields": ["Spotlight Job"],
    }
    second = {
        "title": "Analog Design Engineer",
        "externalPath": "/job/Austin/Analog-Design-Engineer_JR0270002",
        "bulletFields": ["Spotlight Job"],
    }

    first_id = collector._parse_job(first, None).source_job_id
    second_id = collector._parse_job(second, None).source_job_id

    assert first_id == "JR0270001"
    assert second_id == "JR0270002"
    assert first_id != second_id


def test_prefers_detail_start_date_over_relative_text(workday_fixture):
    """Should use the absolute startDate when the detail record supplies one."""
    collector = make_collector()
    summary = workday_fixture["search"]["jobPostings"][1]
    detail = workday_fixture["detail"]["jobPostingInfo"]

    job = collector._parse_job(summary, detail)

    assert job.date_posted == datetime(2026, 7, 28)


def test_falls_back_to_relative_posted_on(workday_fixture):
    """Should derive a date from 'Posted 5 Days Ago' when no detail exists."""
    collector = make_collector()
    summary = workday_fixture["search"]["jobPostings"][0]

    job = collector._parse_job(summary, None)

    assert job.date_posted is not None
    delta = datetime.utcnow() - job.date_posted
    assert 4.9 < delta.days + delta.seconds / 86400 < 5.1


@pytest.mark.parametrize(
    "text,expected_days",
    [
        ("Posted Today", 0),
        ("Posted Yesterday", 1),
        ("Posted 5 Days Ago", 5),
        ("Posted 30+ Days Ago", 30),
    ],
)
def test_parse_posted_on_variants(text, expected_days):
    """Should handle Workday's relative date phrasings."""
    now = datetime(2026, 8, 2, 12, 0, 0)

    parsed = WorkdayCollector._parse_posted_on(text, now=now)

    assert parsed is not None
    assert (now - parsed).days == expected_days


def test_parse_posted_on_unparseable():
    """Should return None rather than guessing on unknown phrasing."""
    assert WorkdayCollector._parse_posted_on("Posted a while back") is None
    assert WorkdayCollector._parse_posted_on("") is None


@pytest.mark.parametrize(
    "time_type,title,expected",
    [
        ("Full time", "Electrician Helper", EmploymentType.FULL_TIME),
        ("Part time", "Analyst", EmploymentType.PART_TIME),
        ("Contract", "Contractor", EmploymentType.CONTRACT),
        ("Seasonal", "Groundskeeper", EmploymentType.TEMPORARY),
        ("", "Unknown Role", EmploymentType.UNKNOWN),
        ("Full time", "Electrician Apprentice", EmploymentType.APPRENTICESHIP),
    ],
)
def test_employment_type_mapping(time_type, title, expected):
    """Should map timeType, with apprenticeship titles taking precedence."""
    assert WorkdayCollector._parse_employment_type(time_type, title) == expected


@pytest.mark.parametrize(
    "location,title,expected",
    [
        ("Austin, TX - Hybrid", "Developer", RemoteStatus.HYBRID),
        ("Remote", "Developer", RemoteStatus.REMOTE),
        ("Austin Energy", "Electrician Helper", RemoteStatus.UNKNOWN),
        ("Austin, TX", "Remote Software Engineer", RemoteStatus.REMOTE),
    ],
)
def test_remote_status_mapping(location, title, expected):
    """Should infer remote status from location and title text."""
    assert WorkdayCollector._parse_remote_status(location, title) == expected


def test_store_raw_disabled_by_default(workday_fixture):
    """Should omit raw payload unless explicitly requested."""
    collector = make_collector()
    summary = workday_fixture["search"]["jobPostings"][0]

    assert collector._parse_job(summary, None).raw_payload == {}


def test_store_raw_when_enabled(workday_fixture):
    """Should retain both summary and detail when store_raw is set."""
    collector = make_collector(parsing_config={"store_raw": True})
    summary = workday_fixture["search"]["jobPostings"][1]
    detail = workday_fixture["detail"]["jobPostingInfo"]

    job = collector._parse_job(summary, detail)

    assert job.raw_payload["summary"] == summary
    assert job.raw_payload["detail"] == detail
