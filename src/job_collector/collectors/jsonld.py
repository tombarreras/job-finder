"""JSON-LD job board collector."""
from datetime import datetime

from job_collector.collectors.base import JobCollector
from job_collector.models import CollectionResult


class JSONLDCollector(JobCollector):
    """Collects from pages with schema.org JobPosting JSON-LD."""

    async def collect(self) -> CollectionResult:
        """Collect jobs from JSON-LD page."""
        self._log_collection_start()

        try:
            # TODO: Implement JSON-LD page collection
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                warnings=["Not yet implemented"],
                complete=False,
            )
        except Exception as e:
            self.logger.exception("JSON-LD collection failed")
            return CollectionResult(
                jobs=[],
                timestamp=datetime.utcnow(),
                errors=[str(e)],
                complete=False,
            )
