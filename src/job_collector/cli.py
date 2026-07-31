"""Command-line interface for job collector."""
import argparse
import logging
import sys
from pathlib import Path

from job_collector.config import JobCollectorConfig
from job_collector.database import JobDatabase


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
    print("Collect command not yet implemented")
    return 0


def report(args: argparse.Namespace) -> int:
    """Generate reports."""
    print("Report command not yet implemented")
    return 0


def send_email(args: argparse.Namespace) -> int:
    """Send email report."""
    print("Send email command not yet implemented")
    return 0


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
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
