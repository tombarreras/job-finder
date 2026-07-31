"""Automatic source discovery and validation."""
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredSource:
    """Result of source discovery."""
    source_type: str  # greenhouse, lever, ashby, jsonld
    identifier: Optional[str]  # board_token, board_name, or URL
    confidence: float  # 0-1
    evidence: list[str]  # Why we think this is the type


class SourceDiscovery:
    """Auto-detect ATS type and source identifiers."""

    def __init__(self, timeout: int = 30) -> None:
        """Initialize discovery."""
        self.timeout = timeout

    async def discover(self, careers_url: str) -> Optional[DiscoveredSource]:
        """Discover source type and identifier from careers URL."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(careers_url, follow_redirects=True)
                response.raise_for_status()
                html = response.text

                # Try each detection method in order of specificity
                result = self._detect_greenhouse(careers_url, html)
                if result:
                    return result

                result = self._detect_lever(careers_url, html)
                if result:
                    return result

                result = self._detect_ashby(careers_url, html)
                if result:
                    return result

                result = self._detect_jsonld(careers_url, html)
                if result:
                    return result

                return None

        except Exception as e:
            logger.warning(f"Discovery failed for {careers_url}: {e}")
            return None

    @staticmethod
    def _detect_greenhouse(careers_url: str, html: str) -> Optional[DiscoveredSource]:
        """Detect Greenhouse."""
        evidence = []

        # Check URL pattern
        if "boards.greenhouse.io" in careers_url:
            match = re.search(r"boards\.greenhouse\.io/([^/]+)", careers_url)
            if match:
                board_token = match.group(1)
                return DiscoveredSource(
                    source_type="greenhouse",
                    identifier=board_token,
                    confidence=0.95,
                    evidence=["URL matches boards.greenhouse.io pattern"],
                )

        # Check for Greenhouse branding in HTML
        if "Powered by Greenhouse" in html or "greenhouse.io" in html:
            evidence.append("HTML contains Greenhouse branding")

            # Try to extract board token from JavaScript
            match = re.search(r"board_token['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", html)
            if match:
                board_token = match.group(1)
                return DiscoveredSource(
                    source_type="greenhouse",
                    identifier=board_token,
                    confidence=0.85,
                    evidence=evidence,
                )

            # Try to extract from iframe or script src
            match = re.search(r"boards\.greenhouse\.io/([^/\"']+)", html)
            if match:
                board_token = match.group(1)
                return DiscoveredSource(
                    source_type="greenhouse",
                    identifier=board_token,
                    confidence=0.75,
                    evidence=evidence + ["Found board token in HTML"],
                )

        return None

    @staticmethod
    def _detect_lever(careers_url: str, html: str) -> Optional[DiscoveredSource]:
        """Detect Lever."""
        evidence = []

        # Check URL pattern
        if "jobs.lever.co" in careers_url:
            match = re.search(r"jobs\.lever\.co/([^/]+)", careers_url)
            if match:
                board_name = match.group(1)
                return DiscoveredSource(
                    source_type="lever",
                    identifier=board_name,
                    confidence=0.95,
                    evidence=["URL matches jobs.lever.co pattern"],
                )

        # Check for Lever branding
        if "lever.co" in html or "Lever" in html and "job" in html:
            evidence.append("HTML contains Lever branding")

            # Try to extract from JavaScript
            match = re.search(r"lever\.co/([^/\"']+)", html)
            if match:
                board_name = match.group(1)
                return DiscoveredSource(
                    source_type="lever",
                    identifier=board_name,
                    confidence=0.8,
                    evidence=evidence,
                )

        return None

    @staticmethod
    def _detect_ashby(careers_url: str, html: str) -> Optional[DiscoveredSource]:
        """Detect Ashby."""
        evidence = []

        # Check URL pattern
        if "ashby" in careers_url.lower():
            if "jobs.ashby.co" in careers_url or "careers.ashby.co" in careers_url:
                match = re.search(r"ashby\.co/([^/]+)", careers_url)
                if match:
                    board_name = match.group(1)
                    return DiscoveredSource(
                        source_type="ashby",
                        identifier=board_name,
                        confidence=0.95,
                        evidence=["URL matches ashby.co pattern"],
                    )

        # Check for Ashby branding
        if "ashby" in html.lower():
            evidence.append("HTML contains Ashby reference")

            match = re.search(r"ashby\.co/([^/\"']+)", html)
            if match:
                board_name = match.group(1)
                return DiscoveredSource(
                    source_type="ashby",
                    identifier=board_name,
                    confidence=0.8,
                    evidence=evidence,
                )

        return None

    @staticmethod
    def _detect_jsonld(careers_url: str, html: str) -> Optional[DiscoveredSource]:
        """Detect JSON-LD JobPosting."""
        # Look for JSON-LD blocks
        pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
        matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)

        for match in matches:
            try:
                data = json.loads(match)

                # Check if it's a JobPosting
                if isinstance(data, dict):
                    if data.get("@type") == "JobPosting" or "JobPosting" in str(
                        data.get("@type", [])
                    ):
                        return DiscoveredSource(
                            source_type="jsonld",
                            identifier=careers_url,
                            confidence=0.9,
                            evidence=["Found JobPosting JSON-LD"],
                        )

                    # Check @graph
                    if "@graph" in data:
                        for item in data["@graph"]:
                            if item.get("@type") == "JobPosting":
                                return DiscoveredSource(
                                    source_type="jsonld",
                                    identifier=careers_url,
                                    confidence=0.9,
                                    evidence=["Found JobPosting in @graph"],
                                )

                # Check arrays
                elif isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "JobPosting":
                            return DiscoveredSource(
                                source_type="jsonld",
                                identifier=careers_url,
                                confidence=0.9,
                                evidence=["Found JobPosting in array"],
                            )

            except json.JSONDecodeError:
                continue

        return None

    async def test_source(
        self,
        source_type: str,
        identifier: str,
    ) -> bool:
        """Test if a source can be accessed and returns jobs."""
        try:
            if source_type == "greenhouse":
                return await self._test_greenhouse(identifier)
            elif source_type == "lever":
                return await self._test_lever(identifier)
            elif source_type == "ashby":
                return await self._test_ashby(identifier)
            elif source_type == "jsonld":
                return await self._test_jsonld(identifier)
        except Exception as e:
            logger.debug(f"Source test failed: {e}")

        return False

    async def _test_greenhouse(self, board_token: str) -> bool:
        """Test Greenhouse source."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?per_page=1"
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                return len(data.get("jobs", [])) > 0
        return False

    async def _test_lever(self, board_name: str) -> bool:
        """Test Lever source."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            url = f"https://api.lever.co/v0/postings/{board_name}?limit=1"
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                return len(data.get("data", [])) > 0
        return False

    async def _test_ashby(self, board_name: str) -> bool:
        """Test Ashby source."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            url = "https://api.ashby.io/public/openings"
            payload = {"organizationName": board_name}
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                return len(data.get("results", [])) > 0
        return False

    async def _test_jsonld(self, careers_url: str) -> bool:
        """Test JSON-LD source."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(careers_url)
                if response.status_code == 200:
                    # Check if there's JSON-LD with JobPosting
                    pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
                    matches = re.findall(
                        pattern, response.text, re.DOTALL | re.IGNORECASE
                    )
                    for match in matches:
                        try:
                            data = json.loads(match)
                            if self._contains_job_posting(data):
                                return True
                        except json.JSONDecodeError:
                            continue
        except Exception:
            pass

        return False

    @staticmethod
    def _contains_job_posting(data: dict) -> bool:
        """Check if data contains JobPosting."""
        if data.get("@type") == "JobPosting":
            return True
        if "@graph" in data:
            for item in data["@graph"]:
                if item.get("@type") == "JobPosting":
                    return True
        return False


async def discover_and_test_companies(
    companies: list[dict],
) -> list[dict]:
    """Discover sources for multiple companies."""
    discovery = SourceDiscovery()
    results = []

    for company in companies:
        careers_url = company.get("career_page_url") or company.get("careers_url")
        if not careers_url:
            logger.warning(f"No careers URL for {company['name']}")
            results.append({**company, "discovery_result": "no_url"})
            continue

        logger.info(f"Discovering {company['name']}...")

        # Discover source type
        discovered = await discovery.discover(careers_url)

        if not discovered:
            logger.warning(f"Could not detect source type for {company['name']}")
            results.append({**company, "discovery_result": "detection_failed"})
            continue

        logger.info(
            f"  Detected: {discovered.source_type} (confidence: {discovered.confidence})"
        )

        # Test the source
        can_access = await discovery.test_source(
            discovered.source_type, discovered.identifier
        )

        if can_access:
            logger.info(f"  ✓ Source accessible and returns jobs")
            company["sources"] = [
                {
                    "type": discovered.source_type,
                    discovered.source_type: discovered.identifier
                    if discovered.source_type != "jsonld"
                    else None,
                    "site_url": discovered.identifier
                    if discovered.source_type == "jsonld"
                    else None,
                    "enabled": True,
                }
            ]
            company["enabled"] = True
            results.append({**company, "discovery_result": "success"})
        else:
            logger.warning(f"  ✗ Source not accessible or returns no jobs")
            company["sources"] = [
                {
                    "type": discovered.source_type,
                    discovered.source_type: discovered.identifier
                    if discovered.source_type != "jsonld"
                    else None,
                    "site_url": discovered.identifier
                    if discovered.source_type == "jsonld"
                    else None,
                    "enabled": False,
                }
            ]
            company["enabled"] = False
            results.append({**company, "discovery_result": "no_access"})

    return results
