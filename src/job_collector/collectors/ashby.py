"""Ashby job board collector."""
from datetime import datetime

from job_collector.collectors.base import JobCollector
from job_collector.models import CollectionResult


class AshbyCollector(JobCollector):
    """Collects from Ashby public job boards."""

    async def collect(self) -> CollectionResult:
        """Collect jobs from Ashby board."""
        self._log_collection_start()

        try:
            # TODO: Implement Ashby API collection
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                warnings=["Not yet implemented"],
                complete=False,
            )
        except Exception as e:
            self.logger.exception("Ashby collection failed")
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                errors=[str(e)],
                complete=False,
            )
