"""Lever job board collector."""
from datetime import datetime

from job_collector.collectors.base import JobCollector
from job_collector.models import CollectionResult


class LeverCollector(JobCollector):
    """Collects from Lever public job boards."""

    async def collect(self) -> CollectionResult:
        """Collect jobs from Lever board."""
        self._log_collection_start()

        try:
            # TODO: Implement Lever API collection
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                warnings=["Not yet implemented"],
                complete=False,
            )
        except Exception as e:
            self.logger.exception("Lever collection failed")
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                errors=[str(e)],
                complete=False,
            )
