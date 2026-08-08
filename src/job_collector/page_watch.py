"""Watch pages that publish application windows rather than job postings.

Union halls and apprenticeship programmes (IBEW 520, Austin ETA, CenTex IEC)
announce when applications open; they have no job board to collect. Detecting
that such a page changed is the signal.

Reporting a bare "it changed" would be near useless, so the previous text is
stored and only the *added* text is reported. That also suppresses the common
false positive where a hash flips but nothing meaningful was added.
"""
import asyncio
import difflib
import hashlib
import html as html_lib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

from job_collector.database import JobDatabase, connect

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

#: Below this many added characters a change is treated as noise. Rotating
#: banners and counters trip the hash without adding anything to read.
MIN_MEANINGFUL_CHARS = 40

#: Some sites serve a "page not found" body with HTTP 200 (centexiec.com does),
#: which would leave us silently watching an error page for months.
SOFT_404_RE = re.compile(
    r"404 page|page not found|page can'?t be found|page cannot be found|"
    r"page you (?:are|were) looking for (?:could not|can'?t)", re.I
)


@dataclass
class WatchConfig:
    """A page to watch."""
    id: str
    name: str
    url: str
    keywords: list[str] = field(default_factory=list)
    enabled: bool = True
    timeout_seconds: int = 30


@dataclass
class WatchResult:
    """Outcome of checking one page."""
    id: str
    name: str
    url: str
    status: str  # new | changed | unchanged | error
    added_text: str = ""
    keywords_found: list[str] = field(default_factory=list)
    last_changed_at: Optional[str] = None
    error: str = ""


def load_watches(config_dir: Path | str) -> list[WatchConfig]:
    """Load watch definitions; an absent file simply means no watches."""
    path = Path(config_dir) / "watches.yaml"
    if not path.exists():
        return []

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    watches = []
    for entry in data.get("watches") or []:
        if not entry.get("enabled", True):
            continue
        watches.append(
            WatchConfig(
                id=entry["id"],
                name=entry.get("name", entry["id"]),
                url=entry["url"],
                keywords=entry.get("keywords", []),
                timeout_seconds=entry.get("timeout_seconds", 30),
            )
        )
    return watches


def extract_text(html: str) -> str:
    """Reduce a page to its visible text.

    Scripts and styles change constantly (nonces, build hashes) and would make
    every check look like a change.
    """
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    text = re.sub(r"<[^>]+>", "\n", html)
    text = html_lib.unescape(text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def added_lines(previous: str, current: str) -> str:
    """Text present now but not before."""
    diff = difflib.ndiff(previous.splitlines(), current.splitlines())
    return "\n".join(line[2:] for line in diff if line.startswith("+ ")).strip()


class PageWatcher:
    """Checks watched pages and records their state."""

    def __init__(self, database: JobDatabase) -> None:
        self.database = database

    async def check_all(self, watches: list[WatchConfig]) -> list[WatchResult]:
        """Check every watch concurrently."""
        if not watches:
            return []
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        ) as client:
            return list(await asyncio.gather(*(self._check(client, w) for w in watches)))

    async def _check(self, client: httpx.AsyncClient, watch: WatchConfig) -> WatchResult:
        try:
            response = await client.get(watch.url, timeout=watch.timeout_seconds)
            response.raise_for_status()
        except Exception as e:
            logger.warning(f"Watch {watch.id} failed: {e}")
            self._record_error(watch, str(e))
            return WatchResult(watch.id, watch.name, watch.url, "error", error=str(e))

        text = extract_text(response.text)

        # A soft 404 is a misconfigured watch, not a page worth diffing.
        if SOFT_404_RE.search(text[:2000]):
            message = f"page returned 200 but looks like a 404: {response.url}"
            logger.warning(f"Watch {watch.id}: {message}")
            self._record_error(watch, message)
            return WatchResult(watch.id, watch.name, watch.url, "error", error=message)

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        previous = self._load(watch.id)
        now = datetime.utcnow().isoformat()

        if previous is None:
            self._save(watch, digest, text, now, changed_at=now, status="new")
            return WatchResult(watch.id, watch.name, watch.url, "new", last_changed_at=now)

        prev_hash, prev_text, prev_changed_at = previous
        if digest == prev_hash:
            self._touch(watch.id, now)
            return WatchResult(
                watch.id, watch.name, watch.url, "unchanged", last_changed_at=prev_changed_at
            )

        added = added_lines(prev_text or "", text)
        if len(added) < MIN_MEANINGFUL_CHARS:
            # Store the new text so the diff does not re-trigger, but do not
            # report a change nobody can act on.
            self._save(watch, digest, text, now, changed_at=prev_changed_at, status="unchanged")
            return WatchResult(
                watch.id, watch.name, watch.url, "unchanged", last_changed_at=prev_changed_at
            )

        self._save(watch, digest, text, now, changed_at=now,
                   status="changed", added_text=added)
        lowered = added.lower()
        found = [k for k in watch.keywords if k.lower() in lowered]
        return WatchResult(
            watch.id, watch.name, watch.url, "changed",
            added_text=added, keywords_found=found, last_changed_at=now,
        )

    # --- persistence ---------------------------------------------------

    def _load(self, watch_id: str) -> Optional[tuple[str, str, str]]:
        with connect(self.database.db_path) as conn:
            row = conn.execute(
                "SELECT content_hash, content_text, last_changed_at FROM page_watches WHERE id = ?",
                (watch_id,),
            ).fetchone()
        return row

    def _save(self, watch: WatchConfig, digest: str, text: str,
              checked_at: str, changed_at: str,
              status: str = "ok", added_text: str = "") -> None:
        with connect(self.database.db_path) as conn:
            conn.execute(
                """
                INSERT INTO page_watches
                    (id, url, name, content_hash, content_text,
                     first_seen_at, last_checked_at, last_changed_at,
                     last_status, last_error, last_added_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)
                ON CONFLICT(id) DO UPDATE SET
                    url = excluded.url,
                    name = excluded.name,
                    content_hash = excluded.content_hash,
                    content_text = excluded.content_text,
                    last_checked_at = excluded.last_checked_at,
                    last_changed_at = excluded.last_changed_at,
                    last_status = excluded.last_status,
                    last_error = '',
                    last_added_text = excluded.last_added_text
                """,
                (watch.id, watch.url, watch.name, digest, text,
                 checked_at, checked_at, changed_at, status, added_text),
            )

    def _touch(self, watch_id: str, checked_at: str) -> None:
        with connect(self.database.db_path) as conn:
            conn.execute(
                "UPDATE page_watches SET last_checked_at = ?, last_status = 'unchanged' WHERE id = ?",
                (checked_at, watch_id),
            )

    def _record_error(self, watch: WatchConfig, error: str) -> None:
        with connect(self.database.db_path) as conn:
            conn.execute(
                """
                INSERT INTO page_watches (id, url, name, last_checked_at, last_status, last_error)
                VALUES (?, ?, ?, ?, 'error', ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_checked_at = excluded.last_checked_at,
                    last_status = 'error',
                    last_error = excluded.last_error
                """,
                (watch.id, watch.url, watch.name, datetime.utcnow().isoformat(), error[:500]),
            )
