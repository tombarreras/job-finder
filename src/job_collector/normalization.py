"""Job normalization utilities."""
import hashlib
import html
import re
from typing import Any


def normalize_title(title: str) -> str:
    """Normalize job title for comparison."""
    title = title.lower().strip()
    # Remove common suffixes
    title = re.sub(r'\s*\(.*?\)\s*$', '', title)
    title = re.sub(r'\s*-\s*(urgent|new|posted).*?$', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s+', ' ', title)
    return title


def normalize_location(location: str) -> str:
    """Normalize location for comparison."""
    location = location.lower().strip()
    # Remove country codes and common suffixes
    location = re.sub(r'\s*,\s*US[A]?\s*$', '', location, flags=re.IGNORECASE)
    # Parenthetical notes ("San Francisco (Bay Area), CA") can appear mid-string,
    # not just at the end.
    location = re.sub(r'\s*\([^)]*\)', '', location)
    location = re.sub(r'\s+', ' ', location)
    return location.strip()


def normalize_company(company: str) -> str:
    """Normalize company name for comparison."""
    company = company.lower().strip()
    company = re.sub(r'\s+', ' ', company)
    return company


def clean_html(text: str) -> str:
    """Convert HTML to plain text."""
    # Unescape HTML entities
    text = html.unescape(text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '\n', text)
    # Clean up whitespace
    text = re.sub(r'\n\s*\n', '\n', text)
    text = '\n'.join(line.strip() for line in text.split('\n') if line.strip())
    return text


def truncate_text(text: str, max_length: int = 2000) -> str:
    """Truncate text to at most max_length characters, including any ellipsis."""
    if len(text) <= max_length:
        return text

    # Try to truncate at a sentence boundary
    truncated = text[:max_length]
    last_period = truncated.rfind('.')
    if last_period > max_length * 0.8:
        return truncated[:last_period + 1]

    # Leave room for the ellipsis rather than overshooting max_length.
    return truncated[:max_length - 3] + "..."


def calculate_content_hash(
    company_name: str,
    title: str,
    location: str,
    description: str,
    apply_url: str,
) -> str:
    """Calculate stable hash of job content."""
    content = f"{company_name}|{title}|{location}|{description}|{apply_url}"
    return hashlib.sha256(content.encode()).hexdigest()


def generate_fingerprint(
    company_name: str,
    title: str,
    location: str,
    apply_url: str,
) -> str:
    """Generate fingerprint for cross-source duplicate detection."""
    normalized = f"{normalize_company(company_name)}|{normalize_title(title)}|{normalize_location(location)}|{apply_url}"
    return hashlib.md5(normalized.encode()).hexdigest()
