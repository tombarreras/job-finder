"""Configuration loading and validation."""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SourceConfig:
    """Configuration for a single job source."""
    type: str
    enabled: bool = True
    timeout_seconds: int = 30
    tags: list[str] = field(default_factory=list)
    location_overrides: list[str] = field(default_factory=list)
    parsing_config: dict[str, Any] = field(default_factory=dict)

    # Source-specific identifiers
    board_token: Optional[str] = None
    board_name: Optional[str] = None
    site_url: Optional[str] = None

    # Workday coordinates; also derivable from site_url
    tenant: Optional[str] = None
    wd_host: Optional[str] = None
    site: Optional[str] = None

    # Tracking (stored in DB, not YAML)
    last_successful_check: Optional[str] = None
    last_error: Optional[str] = None


@dataclass
class CompanyConfig:
    """Configuration for a company."""
    id: str
    name: str
    enabled: bool = True
    priority: str = "medium"
    categories: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    sources: list[SourceConfig] = field(default_factory=list)
    notes: str = ""
    career_page_url: Optional[str] = None
    email_alert_url: Optional[str] = None
    manual_review: bool = False


@dataclass
class SearchRule:
    """Search rule for job categorization."""
    name: str
    nationwide: bool
    locations: list[str] = field(default_factory=list)
    include_titles: list[str] = field(default_factory=list)
    exclude_titles: list[str] = field(default_factory=list)


@dataclass
class JobCollectorConfig:
    """Main configuration for the job collector."""
    companies: list[CompanyConfig] = field(default_factory=list)
    search_rules: dict[str, SearchRule] = field(default_factory=dict)
    database_path: str = "data/jobs.db"
    output_directory: str = "output"
    log_level: str = "INFO"

    @classmethod
    def from_yaml(cls, config_dir: Path | str) -> "JobCollectorConfig":
        """Load configuration from YAML files."""
        config_dir = Path(config_dir)

        companies_config = cls._load_yaml(config_dir / "companies.yaml", {})
        search_rules_config = cls._load_yaml(config_dir / "search_rules.yaml", {})

        # Parse companies
        companies = []
        for company_dict in companies_config.get("companies", []):
            sources = []
            for source_dict in company_dict.get("sources", []):
                source = SourceConfig(
                    type=source_dict.get("type", ""),
                    enabled=source_dict.get("enabled", True),
                    timeout_seconds=source_dict.get("timeout_seconds", 30),
                    tags=source_dict.get("tags", []),
                    location_overrides=source_dict.get("location_overrides", []),
                    parsing_config=source_dict.get("parsing_config", {}),
                    board_token=source_dict.get("board_token"),
                    board_name=source_dict.get("board_name"),
                    site_url=source_dict.get("site_url"),
                    tenant=source_dict.get("tenant"),
                    wd_host=source_dict.get("wd_host"),
                    site=source_dict.get("site"),
                )
                sources.append(source)

            company = CompanyConfig(
                id=company_dict["id"],
                name=company_dict.get("name", company_dict["id"]),
                enabled=company_dict.get("enabled", True),
                priority=company_dict.get("priority", "medium"),
                categories=company_dict.get("categories", []),
                locations=company_dict.get("locations", []),
                sources=sources,
                notes=company_dict.get("notes", ""),
                career_page_url=company_dict.get("career_page_url"),
                email_alert_url=company_dict.get("email_alert_url"),
                manual_review=company_dict.get("manual_review", False),
            )
            companies.append(company)

        # Parse search rules
        search_rules = {}
        for rule_name, rule_dict in search_rules_config.items():
            search_rules[rule_name] = SearchRule(
                name=rule_name,
                nationwide=rule_dict.get("nationwide", False),
                locations=rule_dict.get("locations", []),
                include_titles=rule_dict.get("include_titles", []),
                exclude_titles=rule_dict.get("exclude_titles", []),
            )

        return cls(
            companies=companies,
            search_rules=search_rules,
            database_path=companies_config.get("database_path", "data/jobs.db"),
            output_directory=companies_config.get("output_directory", "output"),
            log_level=companies_config.get("log_level", "INFO"),
        )

    @staticmethod
    def _load_yaml(path: Path, default: Any) -> Any:
        """Load YAML file or return default if not found."""
        if not path.exists():
            logger.warning(f"Config file not found: {path}")
            return default
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data or default

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if not self.companies:
            errors.append("No companies configured")

        for company in self.companies:
            if not company.id:
                errors.append(f"Company missing ID: {company.name}")
            if not company.sources:
                errors.append(f"Company {company.id} has no sources")
            for source in company.sources:
                if source.type not in ["greenhouse", "lever", "ashby", "jsonld", "workday"]:
                    errors.append(f"Unknown source type: {source.type}")
                if source.type == "workday" and not (
                    (source.tenant and source.site) or source.site_url
                ):
                    errors.append(
                        f"Company {company.id}: workday source needs tenant + site "
                        f"(or a site_url to derive them from)"
                    )

        return errors
