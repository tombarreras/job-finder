"""Greenhouse job board collector."""
from datetime import datetime

from job_collector.collectors.base import JobCollector
from job_collector.models import CollectionResult


class GreenhouseCollector(JobCollector):
    """Collects from Greenhouse public job boards."""

    async def collect(self) -> CollectionResult:
        """Collect jobs from Greenhouse board."""
        self._log_collection_start()

        try:
            # TODO: Implement Greenhouse API collection
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                warnings=["Not yet implemented"],
                complete=False,
            )
        except Exception as e:
            self.logger.exception("Greenhouse collection failed")
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                errors=[str(e)],
                complete=False,
            )
