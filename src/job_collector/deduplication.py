"""Job deduplication logic."""
import hashlib
from typing import Optional

from job_collector.models import NormalizedJob
from job_collector.normalization import (
    calculate_content_hash,
    generate_fingerprint,
    normalize_company,
    normalize_location,
    normalize_title,
)


def find_exact_duplicate(
    new_job: NormalizedJob,
    existing_jobs: dict[str, NormalizedJob],
) -> Optional[NormalizedJob]:
    """Find exact duplicate of new job in existing jobs from same source."""
    for job in existing_jobs.values():
        if job.source_id != new_job.source_id:
            continue

        if job.source_job_id == new_job.source_job_id:
            return job

    return None


def find_cross_source_duplicates(
    new_job: NormalizedJob,
    all_jobs: list[NormalizedJob],
    threshold: float = 0.8,
) -> list[tuple[NormalizedJob, float]]:
    """Find likely duplicates across different sources."""
    candidates = []

    new_fingerprint = generate_fingerprint(
        new_job.company_name,
        new_job.title,
        new_job.location,
        new_job.apply_url,
    )

    for existing_job in all_jobs:
        if existing_job.source_id == new_job.source_id:
            continue

        existing_fingerprint = generate_fingerprint(
            existing_job.company_name,
            existing_job.title,
            existing_job.location,
            existing_job.apply_url,
        )

        if new_fingerprint == existing_fingerprint:
            candidates.append((existing_job, 1.0))
            continue

        # Check for partial matches
        score = _calculate_similarity(new_job, existing_job)
        if score >= threshold:
            candidates.append((existing_job, score))

    return sorted(candidates, key=lambda x: x[1], reverse=True)


def _calculate_similarity(job1: NormalizedJob, job2: NormalizedJob) -> float:
    """Calculate similarity score between two jobs."""
    scores = []

    # Company name similarity
    norm_company1 = normalize_company(job1.company_name)
    norm_company2 = normalize_company(job2.company_name)
    company_match = 1.0 if norm_company1 == norm_company2 else 0.0
    scores.append(company_match * 0.3)

    # Title similarity
    norm_title1 = normalize_title(job1.title)
    norm_title2 = normalize_title(job2.title)
    title_similarity = _string_similarity(norm_title1, norm_title2)
    scores.append(title_similarity * 0.4)

    # Location similarity
    norm_loc1 = normalize_location(job1.location)
    norm_loc2 = normalize_location(job2.location)
    location_match = 1.0 if norm_loc1 == norm_loc2 else 0.0
    scores.append(location_match * 0.2)

    # URL similarity (exact match highest priority)
    url_score = 1.0 if job1.apply_url == job2.apply_url else 0.0
    if url_score < 1.0 and job1.source_url == job2.source_url:
        url_score = 0.9
    scores.append(url_score * 0.1)

    return sum(scores)


def _string_similarity(s1: str, s2: str) -> float:
    """Calculate simple string similarity (0-1)."""
    if s1 == s2:
        return 1.0

    # Levenshtein distance-based similarity
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0

    distance = _levenshtein_distance(s1, s2)
    return 1.0 - (distance / max_len)


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]
