"""Command-line interface for job collector."""
import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from job_collector.config import JobCollectorConfig
from job_collector.database import JobDatabase

logger = logging.getLogger(__name__)


def setup_logging(log_level: str) -> None:
    """Configure logging."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def validate_config(args: argparse.Namespace) -> int:
    """Validate configuration files."""
    config_dir = Path(args.config_dir or "config")
    try:
        config = JobCollectorConfig.from_yaml(config_dir)
        errors = config.validate()

        if errors:
            print("Configuration errors found:")
            for error in errors:
                print(f"  - {error}")
            return 1

        print("Configuration is valid")
        print(f"  Companies: {len(config.companies)}")
        print(f"  Search rules: {len(config.search_rules)}")
        return 0
    except Exception as e:
        print(f"Failed to load configuration: {e}")
        return 1


def init_db(args: argparse.Namespace) -> int:
    """Initialize database."""
    db_path = Path(args.database or "data/jobs.db")
    try:
        db = JobDatabase(db_path)
        print(f"Database initialized at {db_path}")

        # Load config and set up companies/sources
        config_dir = Path(args.config_dir or "config")
        config = JobCollectorConfig.from_yaml(config_dir)

        for company in config.companies:
            db.add_or_update_company(company.id, company.name, company.enabled)

            for i, source in enumerate(company.sources):
                source_id = f"{company.id}#{source.type}#{i}"
                source_key = (
                    source.board_token
                    or source.board_name
                    or source.site_url
                )
                db.add_or_update_source(source_id, company.id, source.type, source_key)

        print(f"  Companies: {len(config.companies)}")
        total_sources = sum(len(c.sources) for c in config.companies)
        print(f"  Sources: {total_sources}")
        return 0
    except Exception as e:
        print(f"Failed to initialize database: {e}")
        return 1


def collect(args: argparse.Namespace) -> int:
    """Collect jobs from configured sources."""
    import asyncio
    from pathlib import Path

    from job_collector.collection import JobCollectionOrchestrator
    from job_collector.config import JobCollectorConfig
    from job_collector.database import JobDatabase

    config_dir = Path(args.config_dir or "config")
    db_path = Path(args.database or "data/jobs.db")

    try:
        config = JobCollectorConfig.from_yaml(config_dir)
        errors = config.validate()
        if errors:
            print("Configuration errors:")
            for error in errors:
                print(f"  - {error}")
            return 1

        db = JobDatabase(db_path)
        orchestrator = JobCollectionOrchestrator(config, db)

        # Run collection
        result = asyncio.run(orchestrator.collect_all(
            source_filter=args.source if hasattr(args, 'source') and args.source else None,
            company_filter=args.company if hasattr(args, 'company') and args.company else None,
        ))

        # Log results
        print(f"Collection complete: {result['stats']['new_count']} new, "
              f"{result['stats']['changed_count']} changed, "
              f"{result['stats']['expired_count']} expired")
        print(f"Sources: {result['stats']['successful_sources']} successful, "
              f"{result['stats']['failed_sources']} failed")
        print(f"Duration: {result['duration']:.2f}s")

        return 0

    except Exception as e:
        logger.exception("Collection failed")
        print(f"Error: {e}")
        return 1


def report(args: argparse.Namespace) -> int:
    """Generate reports."""
    from pathlib import Path

    from job_collector.config import JobCollectorConfig
    from job_collector.database import JobDatabase
    from job_collector.reporting import ReportGenerator

    config_dir = Path(args.config_dir or "config")
    db_path = Path(args.database or "data/jobs.db")
    output_dir = Path(args.output_directory or "output")

    try:
        config = JobCollectorConfig.from_yaml(config_dir)
        db = JobDatabase(db_path)

        jobs = db.get_recent_jobs()
        source_errors = []

        enabled_sources = [
            s for c in config.companies for s in c.sources if c.enabled and s.enabled
        ]

        generator = ReportGenerator(output_dir)
        json_path, md_path = generator.generate_reports(
            jobs,
            {
                "source_count": len(enabled_sources),
                "successful_sources": len(enabled_sources),
                "failed_sources": 0,
            },
            source_errors,
            include_unchanged=getattr(args, "include_unchanged", False),
        )

        counts = Counter(job.status.value for job in jobs)
        print("Reports generated:")
        print(f"  JSON: {json_path}")
        print(f"  Markdown: {md_path}")
        print(f"  Jobs: {len(jobs)} ({dict(counts)})")
        return 0

    except Exception as e:
        logger.exception("Report generation failed")
        print(f"Error: {e}")
        return 1


def send_email(args: argparse.Namespace) -> int:
    """Send email report."""
    from pathlib import Path

    from job_collector.email_delivery import EmailDelivery

    import os

    from job_collector.database import JobDatabase

    output_dir = Path(args.output_directory or "output")
    db_path = Path(args.database or "data/jobs.db")

    try:
        json_report = output_dir / "latest_jobs.json"
        md_report = output_dir / "latest_report.md"

        if not json_report.exists():
            print("No report found. Run 'report' command first.")
            return 1

        report_content = md_report.read_text(encoding="utf-8")

        # Real counts, rather than the zeros this previously always reported.
        counts: Counter[str] = Counter()
        if db_path.exists():
            counts = Counter(job.status.value for job in JobDatabase(db_path).get_recent_jobs())

        to_address = os.getenv("JOB_EMAIL_TO", "tombarreras@gmail.com")
        new_count = counts.get("new", 0)

        email = EmailDelivery()
        success = email.send_report(
            to_address=to_address,
            subject=f"Christopher Job Collector -- {new_count} new jobs",
            body=EmailDelivery.format_report_email(
                new_count=new_count,
                changed_count=counts.get("changed", 0),
                expired_count=counts.get("expired", 0),
                failed_sources=0,
                markdown_content=report_content,
            ),
            json_report_path=json_report,
        )

        if success:
            print("Email sent successfully")
            return 0
        else:
            print("Failed to send email")
            return 1

    except Exception as e:
        logger.exception("Email delivery failed")
        print(f"Error: {e}")
        return 1


def discover_sources(args: argparse.Namespace) -> int:
    """Auto-discover and validate all company sources."""
    import asyncio
    from pathlib import Path

    from job_collector.discovery_cli import auto_discover_sources

    config_dir = Path(args.config_dir or "config")

    try:
        return asyncio.run(auto_discover_sources(config_dir))
    except Exception as e:
        logger.exception("Source discovery failed")
        print(f"Error: {e}")
        return 1


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Job collection system for tracking employment opportunities"
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument(
        "--config", dest="config_dir", default="config", help="Configuration directory"
    )
    parser.add_argument(
        "--database", default="data/jobs.db", help="Database path"
    )
    parser.add_argument(
        "--output", dest="output_directory", default="output", help="Output directory"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # validate-config command
    subparsers.add_parser("validate-config", help="Validate configuration files")

    # init-db command
    subparsers.add_parser("init-db", help="Initialize database")

    # collect command
    collect_parser = subparsers.add_parser("collect", help="Collect jobs from sources")
    collect_parser.add_argument(
        "--source", help="Collect from specific source type"
    )
    collect_parser.add_argument(
        "--company", help="Collect from specific company"
    )
    collect_parser.add_argument(
        "--dry-run", action="store_true", help="Dry run without updating state"
    )
    collect_parser.add_argument(
        "--since", help="Only process changes since timestamp"
    )
    collect_parser.add_argument(
        "--include-unchanged", action="store_true", help="Include unchanged jobs in output"
    )

    # report command
    subparsers.add_parser("report", help="Generate reports")

    # send-email command
    subparsers.add_parser("send-email", help="Send email report")

    # discover-sources command
    subparsers.add_parser(
        "discover-sources",
        help="Auto-discover and validate all company sources (takes 5-10 minutes)"
    )

    args = parser.parse_args()
    setup_logging(args.log_level)

    # Route to command handlers
    if args.command == "validate-config":
        return validate_config(args)
    elif args.command == "init-db":
        return init_db(args)
    elif args.command == "collect":
        return collect(args)
    elif args.command == "report":
        return report(args)
    elif args.command == "send-email":
        return send_email(args)
    elif args.command == "discover-sources":
        return discover_sources(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
