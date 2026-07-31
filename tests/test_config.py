"""Tests for configuration loading and validation."""
from pathlib import Path

import pytest

from job_collector.config import JobCollectorConfig, SourceConfig


def test_load_config(temp_config_dir):
    """Should load configuration from YAML files."""
    # Create minimal config files
    companies_yaml = temp_config_dir / "companies.yaml"
    companies_yaml.write_text("""
companies:
  - id: test-company
    name: Test Company
    enabled: true
    priority: high
    categories:
      - software
    locations:
      - Austin, TX
    sources:
      - type: greenhouse
        board_token: testcompany
""")

    search_rules_yaml = temp_config_dir / "search_rules.yaml"
    search_rules_yaml.write_text("""
software:
  nationwide: true
  include_titles:
    - software engineer
""")

    config = JobCollectorConfig.from_yaml(temp_config_dir)

    assert len(config.companies) == 1
    assert config.companies[0].id == "test-company"
    assert config.companies[0].name == "Test Company"
    assert len(config.companies[0].sources) == 1
    assert config.companies[0].sources[0].type == "greenhouse"


def test_config_validation_missing_companies():
    """Should validate that companies are configured."""
    config = JobCollectorConfig()
    errors = config.validate()
    assert any("No companies configured" in e for e in errors)


def test_config_validation_missing_sources(temp_config_dir):
    """Should validate that companies have sources."""
    companies_yaml = temp_config_dir / "companies.yaml"
    companies_yaml.write_text("""
companies:
  - id: test-company
    name: Test Company
""")

    search_rules_yaml = temp_config_dir / "search_rules.yaml"
    search_rules_yaml.write_text("{}")

    config = JobCollectorConfig.from_yaml(temp_config_dir)
    errors = config.validate()

    assert any("has no sources" in e for e in errors)


def test_config_validation_invalid_source_type(temp_config_dir):
    """Should validate source types."""
    companies_yaml = temp_config_dir / "companies.yaml"
    companies_yaml.write_text("""
companies:
  - id: test-company
    name: Test Company
    sources:
      - type: invalid_type
""")

    search_rules_yaml = temp_config_dir / "search_rules.yaml"
    search_rules_yaml.write_text("{}")

    config = JobCollectorConfig.from_yaml(temp_config_dir)
    errors = config.validate()

    assert any("Unknown source type" in e for e in errors)


def test_config_missing_files(temp_config_dir):
    """Should handle missing config files gracefully."""
    config = JobCollectorConfig.from_yaml(temp_config_dir)
    # Should have empty companies list but not crash
    assert isinstance(config.companies, list)


def test_source_config_defaults():
    """Should apply defaults to source config."""
    source = SourceConfig(type="greenhouse")

    assert source.enabled is True
    assert source.timeout_seconds == 30
    assert source.tags == []
    assert source.location_overrides == []
