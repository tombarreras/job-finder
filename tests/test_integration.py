"""Integration tests for the job collection system."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from job_collector.collection import JobCollectionOrchestrator
from job_collector.config import CompanyConfig, JobCollectorConfig, SourceConfig
from job_collector.database import JobDatabase
from job_collector.models import EmploymentType, RemoteStatus


@pytest.mark.asyncio
async def test_end_to_end_collection(temp_db, tmp_path):
    """Test complete collection workflow."""
    # Setup
    config = JobCollectorConfig(
        database_path=str(temp_db),
        output_directory=str(tmp_path),
    )

    config.companies = [
        CompanyConfig(
            id="test-company",
            name="Test Company",
            enabled=True,
            sources=[
                SourceConfig(
                    type="greenhouse",
                    board_token="testcompany",
                    enabled=True,
                )
            ],
        )
    ]

    db = JobDatabase(temp_db)
    orchestrator = JobCollectionOrchestrator(config, db)

    # Mock the collector
    with patch(
        "job_collector.collection.GreenhouseCollector.collect"
    ) as mock_collect:
        from job_collector.models import CollectionResult, NormalizedJob

        mock_job = NormalizedJob(
            source_type="greenhouse",
            source_company_id="test-company",
            source_job_id="1",
            company_name="Test Company",
            title="Software Engineer",
            location="San Francisco, CA",
            apply_url="https://example.com/apply/1",
            source_url="https://example.com/jobs/1",
            description_text="Test job",
            employment_type=EmploymentType.FULL_TIME,
            remote_status=RemoteStatus.HYBRID,
            content_hash="abc123",
        )

        mock_collect.return_value = CollectionResult(
            jobs=[mock_job],
            timestamp=__import__("datetime").datetime.utcnow(),
            http_status=200,
            complete=True,
        )

        # Run collection
        result = await orchestrator.collect_all()

        # Verify results
        assert result is not None
        assert "jobs" in result
        assert "stats" in result
        assert result["stats"]["source_count"] >= 1


@pytest.mark.asyncio
async def test_concurrent_collection_with_errors(temp_db):
    """Test collection handles errors gracefully."""
    config = JobCollectorConfig(
        database_path=str(temp_db),
        output_directory="output",
    )

    config.companies = [
        CompanyConfig(
            id="company1",
            name="Company 1",
            enabled=True,
            sources=[
                SourceConfig(type="greenhouse", board_token="company1", enabled=True)
            ],
        ),
        CompanyConfig(
            id="company2",
            name="Company 2",
            enabled=True,
            sources=[
                SourceConfig(type="lever", board_name="company2", enabled=True)
            ],
        ),
    ]

    db = JobDatabase(temp_db)
    orchestrator = JobCollectionOrchestrator(config, db)

    # Mock both collectors
    with patch(
        "job_collector.collection.GreenhouseCollector.collect"
    ) as mock_greenhouse, patch(
        "job_collector.collection.LeverCollector.collect"
    ) as mock_lever:
        from job_collector.models import CollectionResult

        # First collector succeeds
        mock_greenhouse.return_value = CollectionResult(
            jobs=[],
            timestamp=__import__("datetime").datetime.utcnow(),
            http_status=200,
            complete=True,
        )

        # Second collector fails
        mock_lever.side_effect = Exception("Network error")

        # Run collection
        result = await orchestrator.collect_all()

        # Verify partial success
        assert result is not None
        assert "jobs" in result
        assert len(orchestrator.results) >= 2


def test_database_state_persistence(temp_db, sample_job):
    """Test job state is persisted and retrieved."""
    db = JobDatabase(temp_db)

    # Add company and source
    db.add_or_update_company("test", "Test", True)
    db.add_or_update_source("source-1", "test", "greenhouse", "test")

    # Save job
    db.save_job(sample_job, "source-1")

    # Verify it was saved
    import sqlite3
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM jobs WHERE source_id = ?", ("source-1",))
        count = cursor.fetchone()[0]

    assert count == 1


def test_collection_config_validation():
    """Test configuration validation."""
    config = JobCollectorConfig()

    # Should have errors with no companies
    errors = config.validate()
    assert len(errors) > 0
    assert any("No companies" in e for e in errors)


def test_config_from_yaml(temp_config_dir):
    """Test loading configuration from YAML."""
    # Create test config files
    companies_yaml = temp_config_dir / "companies.yaml"
    companies_yaml.write_text("""
companies:
  - id: test-company
    name: Test Company
    enabled: true
    sources:
      - type: greenhouse
        board_token: testboard
      - type: lever
        board_name: testlever
""")

    search_rules_yaml = temp_config_dir / "search_rules.yaml"
    search_rules_yaml.write_text("""
test_rule:
  nationwide: true
  include_titles:
    - engineer
""")

    config = JobCollectorConfig.from_yaml(temp_config_dir)

    assert len(config.companies) == 1
    assert config.companies[0].id == "test-company"
    assert len(config.companies[0].sources) == 2
    assert "test_rule" in config.search_rules
