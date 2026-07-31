"""Base collector interface."""
import logging
from abc import ABC, abstractmethod
from datetime import datetime

from job_collector.config import SourceConfig
from job_collector.models import CollectionResult

logger = logging.getLogger(__name__)


class JobCollector(ABC):
    """Base class for job collectors."""

    def __init__(self, company_id: str, source_config: SourceConfig) -> None:
        """Initialize collector."""
        self.company_id = company_id
        self.source_config = source_config
        self.logger = logger

    @abstractmethod
    async def collect(self) -> CollectionResult:
        """Collect jobs from source."""
        pass

    def _log_collection_start(self) -> None:
        """Log start of collection."""
        self.logger.info(
            f"Starting collection from {self.source_config.type} "
            f"for company {self.company_id}"
        )

    def _log_collection_end(
        self,
        duration: float,
        job_count: int,
        http_status: int | None = None,
        error: str | None = None,
    ) -> None:
        """Log end of collection."""
        if error:
            self.logger.error(
                f"Collection failed after {duration:.2f}s: {error} "
                f"(HTTP {http_status})"
            )
        else:
            self.logger.info(
                f"Collection complete in {duration:.2f}s: "
                f"{job_count} jobs (HTTP {http_status})"
            )
