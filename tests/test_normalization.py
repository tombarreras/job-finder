"""Tests for normalization utilities."""
import pytest

from job_collector.normalization import (
    calculate_content_hash,
    clean_html,
    generate_fingerprint,
    normalize_company,
    normalize_location,
    normalize_title,
    truncate_text,
)


class TestTitleNormalization:
    """Tests for title normalization."""

    def test_normalize_title_case(self):
        """Title should be lowercased."""
        assert normalize_title("Senior Software Engineer") == "senior software engineer"

    def test_normalize_title_whitespace(self):
        """Extra whitespace should be removed."""
        assert normalize_title("  Software   Engineer  ") == "software engineer"

    def test_normalize_title_suffix(self):
        """Common suffixes should be removed."""
        assert normalize_title("Software Engineer (URGENT)") == "software engineer"
        assert normalize_title("Software Engineer - NEW") == "software engineer"

    def test_normalize_title_similarity(self):
        """Similar titles should normalize to same value."""
        t1 = normalize_title("Junior Software Developer")
        t2 = normalize_title("junior software developer")
        assert t1 == t2


class TestLocationNormalization:
    """Tests for location normalization."""

    def test_normalize_location_case(self):
        """Location should be lowercased."""
        assert normalize_location("San Francisco, CA") == "san francisco, ca"

    def test_normalize_location_country(self):
        """Country code should be removed."""
        assert normalize_location("San Francisco, CA, USA") == "san francisco, ca"

    def test_normalize_location_parentheses(self):
        """Parenthetical notes should be removed."""
        assert normalize_location("San Francisco (Bay Area), CA") == "san francisco, ca"


class TestCompanyNormalization:
    """Tests for company name normalization."""

    def test_normalize_company_case(self):
        """Company should be lowercased."""
        assert normalize_company("Google Inc.") == "google inc."

    def test_normalize_company_whitespace(self):
        """Extra whitespace should be removed."""
        assert normalize_company("  Google   Inc.  ") == "google inc."


class TestHtmlCleaning:
    """Tests for HTML cleaning."""

    def test_clean_html_tags(self):
        """HTML tags should be removed."""
        html = "<p>This is <strong>bold</strong> text</p>"
        result = clean_html(html)
        assert "<" not in result
        assert "bold" in result
        assert "text" in result

    def test_clean_html_entities(self):
        """HTML entities should be decoded."""
        html = "Salary: $100,000 &mdash; $150,000"
        result = clean_html(html)
        assert "—" in result

    def test_clean_html_whitespace(self):
        """Excessive whitespace should be cleaned."""
        html = "<p>Line 1</p>\n\n\n<p>Line 2</p>"
        result = clean_html(html)
        assert result.count("\n") <= 2


class TestTextTruncation:
    """Tests for text truncation."""

    def test_truncate_short_text(self):
        """Short text should not be truncated."""
        text = "Short text"
        assert truncate_text(text, 100) == text

    def test_truncate_long_text(self):
        """Long text should be truncated."""
        text = "A" * 3000
        result = truncate_text(text, 2000)
        assert len(result) <= 2001  # Allow for "..."

    def test_truncate_at_sentence(self):
        """Should truncate at sentence boundary when possible."""
        text = "First sentence. Second sentence that is very long."
        result = truncate_text(text, 30)
        assert result.endswith(".")


class TestContentHash:
    """Tests for content hashing."""

    def test_content_hash_consistency(self):
        """Same content should produce same hash."""
        hash1 = calculate_content_hash("Company", "Title", "Location", "Desc", "URL")
        hash2 = calculate_content_hash("Company", "Title", "Location", "Desc", "URL")
        assert hash1 == hash2

    def test_content_hash_difference(self):
        """Different content should produce different hash."""
        hash1 = calculate_content_hash("Company", "Title", "Location", "Desc", "URL")
        hash2 = calculate_content_hash("Company", "Title", "Location", "Desc", "URL2")
        assert hash1 != hash2


class TestFingerprint:
    """Tests for fingerprinting."""

    def test_fingerprint_normalization(self):
        """Fingerprint should normalize input."""
        fp1 = generate_fingerprint("Google Inc.", "Senior Engineer", "San Francisco, CA", "https://apply.com/1")
        fp2 = generate_fingerprint("google inc.", "senior engineer", "san francisco, ca", "https://apply.com/1")
        # Fingerprints should be the same due to normalization
        assert fp1 == fp2

    def test_fingerprint_consistency(self):
        """Same input should produce same fingerprint."""
        fp1 = generate_fingerprint("Company", "Title", "Location", "URL")
        fp2 = generate_fingerprint("Company", "Title", "Location", "URL")
        assert fp1 == fp2
