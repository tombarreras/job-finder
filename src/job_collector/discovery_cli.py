"""CLI for automated source discovery."""
import asyncio
import json
import logging
from pathlib import Path

import yaml

from job_collector.source_discovery import discover_and_test_companies

logger = logging.getLogger(__name__)


async def auto_discover_sources(
    config_path: Path,
    output_path: Path | None = None,
) -> int:
    """Auto-discover and validate all companies."""
    if output_path is None:
        output_path = config_path / "companies_discovered.yaml"

    # Load current companies
    companies_yaml = config_path / "companies.yaml"
    if not companies_yaml.exists():
        print("companies.yaml not found")
        return 1

    with open(companies_yaml) as f:
        config = yaml.safe_load(f)

    companies = config.get("companies", [])
    print(f"Discovering sources for {len(companies)} companies...")
    print("This may take 5-10 minutes. Please wait...\n")

    # Discover and test all
    results = await discover_and_test_companies(companies)

    # Summary
    success = [r for r in results if r.get("discovery_result") == "success"]
    failed = [r for r in results if r.get("discovery_result") == "no_access"]
    detection_failed = [r for r in results if r.get("discovery_result") == "detection_failed"]
    no_url = [r for r in results if r.get("discovery_result") == "no_url"]

    print("\n" + "=" * 60)
    print("DISCOVERY RESULTS")
    print("=" * 60)
    print(f"[OK] Successfully discovered and tested: {len(success)}")
    print(f"[FAIL] Could not access: {len(failed)}")
    print(f"[UNKNOWN] Could not detect source type: {len(detection_failed)}")
    print(f"[SKIP] No careers URL: {len(no_url)}")
    print(f"\nTotal: {len(results)}")

    print("\n" + "=" * 60)
    print("ENABLED SOURCES (Ready to collect from)")
    print("=" * 60)
    for company in success:
        source = company["sources"][0]
        source_type = source["type"]
        if source_type == "jsonld":
            identifier = source.get("site_url", "")[:50]
        else:
            identifier = source.get(f"{source_type}") or source.get("site_url", "")[:50]
        print(f"  [OK] {company['name']}: {source_type} ({identifier})")

    if failed:
        print("\n" + "=" * 60)
        print("UNABLE TO ACCESS (Requires manual investigation)")
        print("=" * 60)
        for company in failed:
            print(f"  [FAIL] {company['name']}")

    if detection_failed:
        print("\n" + "=" * 60)
        print("DETECTION FAILED (Unknown ATS type)")
        print("=" * 60)
        for company in detection_failed:
            url = company.get("career_page_url", "?")
            print(f"  ? {company['name']}: {url}")

    # Write output
    config["companies"] = results
    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"\n✓ Updated configuration written to: {output_path}")
    print("\nTo use these results:")
    print(f"  1. Review the discovered sources above")
    print(f"  2. Backup your current companies.yaml: cp config/companies.yaml config/companies.backup.yaml")
    print(f"  3. Replace with discovered: mv {output_path} config/companies.yaml")
    print(f"  4. Run: python -m job_collector collect --dry-run")
    print(f"  5. If successful, push to GitHub")

    return 0
