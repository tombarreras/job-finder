"""Data models for job postings and configuration."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class JobStatus(str, Enum):
    """Status of a job posting."""
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    EXPIRED = "expired"
    REOPENED = "reopened"
    SOURCE_ERROR = "source_error"


class RemoteStatus(str, Enum):
    """Remote work capability."""
    ON_SITE = "on_site"
    REMOTE = "remote"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class EmploymentType(str, Enum):
    """Type of employment."""
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    APPRENTICESHIP = "apprenticeship"
    UNKNOWN = "unknown"


@dataclass
class NormalizedJob:
    """Normalized job posting across all sources."""
    source_type: str
    source_company_id: str
    source_job_id: str
    company_name: str
    title: str
    location: str
    apply_url: str
    source_url: str
    date_posted: Optional[datetime] = None
    date_updated: Optional[datetime] = None
    description_text: str = ""
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    remote_status: RemoteStatus = RemoteStatus.UNKNOWN
    salary_text: str = ""

    # Required tracking fields
    first_seen_at: datetime = field(default_factory=datetime.utcnow)
    last_seen_at: datetime = field(default_factory=datetime.utcnow)
    content_hash: str = ""
    status: JobStatus = JobStatus.NEW

    # Optional fields
    department: str = ""
    team: str = ""
    workplace_type: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = "USD"
    salary_period: str = ""
    education_requirements: str = ""
    experience_requirements: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)

    # Classification fields
    category: str = ""
    entry_level_signal: bool = False
    seniority_warning: bool = False
    location_match: bool = False
    relocation_candidate: bool = False
    remote_candidate: bool = False
    technical_relevance: float = 0.0
    trade_relevance: float = 0.0
    immediate_income_relevance: float = 0.0
    warning_flags: list[str] = field(default_factory=list)

    # Deduplication fields
    possible_duplicate_group: Optional[str] = None
    duplicate_confidence: float = 0.0


@dataclass
class CollectionResult:
    """Result of collecting jobs from a source."""
    jobs: list[NormalizedJob]
    timestamp: datetime
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    http_status: Optional[int] = None
    duration_seconds: float = 0.0
    complete: bool = True
