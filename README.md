# Job Finder - Automated Job Collection System

An automated system for collecting, normalizing, and tracking employment opportunities from multiple ATS platforms and career pages. Designed to complement existing Indeed and Craigslist email alerts.

## Overview

> **Current state and design notes live in [STATUS.md](STATUS.md).** Read it
> before changing collectors, the location filter, or the email format — several
> invariants there fail silently if broken.

The system:
- Collects job postings from Workday, Greenhouse, Lever, Ashby, and JSON-LD
  career pages (Workday and Greenhouse are the ones actually in use)
- Normalizes all postings into a common schema
- Detects new, changed, unchanged, and expired jobs
- Deduplicates postings across sources
- Maintains persistent state in SQLite
- Generates JSON and Markdown reports
- Emails daily summaries via SMTP
- Runs on a schedule via GitHub Actions

## Technology Stack

- **Python 3.12+** - Core language
- **SQLite** - Persistent state storage
- **httpx** - HTTP client for API requests
- **Pydantic** - Data validation
- **PyYAML** - Configuration files
- **pytest** - Testing framework
- **Ruff** - Code linting
- **mypy** - Type checking

## Installation

### Local Setup

1. Clone the repository:
```bash
git clone https://github.com/tombarreras/job-finder.git
cd job-finder
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -e ".[dev]"
```

## Configuration

### Companies Registry

Edit `config/companies.yaml` to define job sources:

```yaml
companies:
  - id: example-greenhouse
    name: Example Company
    enabled: true
    priority: high
    categories:
      - software
      - qa
    locations:
      - Austin, TX
      - Remote
    sources:
      - type: greenhouse
        board_token: examplecompany
```

Each source type has specific identifiers:
- **Greenhouse**: `board_token`
- **Lever**: `board_name`
- **Ashby**: `board_name`
- **JSON-LD**: `site_url`

### Search Rules

Edit `config/search_rules.yaml` to define job categories and filtering:

```yaml
software_and_qa:
  nationwide: true
  include_titles:
    - software engineer
    - qa engineer
  exclude_titles:
    - senior
    - manager
```

### Email Configuration

Set up Gmail credentials via GitHub Actions secrets (do not commit to repository):
- `JOB_EMAIL_SMTP_USERNAME` - Gmail address
- `JOB_EMAIL_SMTP_PASSWORD` - Gmail app password or account password
- `JOB_EMAIL_FROM` - Sender email address

## Usage

### Initialize Database

```bash
python -m job_collector init-db --config config --database data/jobs.db
```

### Validate Configuration

```bash
python -m job_collector validate-config --config config
```

### Collect Jobs

Collect from all sources:
```bash
python -m job_collector collect --config config --database data/jobs.db --output output
```

Collect from specific source type:
```bash
python -m job_collector collect --source greenhouse --config config
```

Collect from specific company:
```bash
python -m job_collector collect --company example-greenhouse --config config
```

Dry run (no state changes):
```bash
python -m job_collector collect --dry-run --config config
```

### Generate Reports

```bash
python -m job_collector report --config config --database data/jobs.db --output output
```

### Send Email Report

```bash
python -m job_collector send-email --config config --output output
```

## Running Tests

```bash
pytest                          # Run all tests
pytest -v                       # Verbose output
pytest tests/test_normalization.py  # Specific test file
pytest -k test_normalize_title  # Specific test
```

Check coverage:
```bash
pytest --cov=src/job_collector
```

## GitHub Actions Setup

### Workflow File

The workflow runs daily at 7:00 AM UTC (11 PM PT previous day, adjusting for daylight saving time):

```bash
# PST (November - March): 7 AM UTC = 11 PM previous day
# PDT (March - November): 7 AM UTC = 12 AM previous day (midnight)
```

### Required Secrets

Set these in your GitHub repository settings:
- `JOB_EMAIL_SMTP_USERNAME` - Gmail address
- `JOB_EMAIL_SMTP_PASSWORD` - Gmail app password
- `JOB_EMAIL_FROM` - Sender email address

### Persistence Strategy

The workflow uses a dedicated `job-search-state` branch to maintain SQLite database across runs:

1. At workflow start, database is fetched from `job-search-state` branch
2. Jobs are collected and state updated
3. Updated database is committed back to `job-search-state`
4. Prevents concurrent writes via workflow concurrency controls

## Architecture

### Directory Structure

```
job-finder/
├── .github/
│   └── workflows/
│       └── collect-jobs.yml
├── config/
│   ├── companies.yaml
│   ├── search_rules.yaml
│   └── email.yaml.example
├── data/
│   └── jobs.db
├── output/
│   ├── latest_jobs.json
│   ├── latest_report.md
│   └── archive/
├── src/
│   └── job_collector/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── database.py
│       ├── models.py
│       ├── normalization.py
│       ├── deduplication.py
│       ├── reporting.py
│       ├── email_delivery.py
│       └── collectors/
│           ├── __init__.py
│           ├── base.py
│           ├── greenhouse.py
│           ├── lever.py
│           ├── ashby.py
│           └── jsonld.py
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_database.py
│   ├── test_deduplication.py
│   ├── test_normalization.py
│   ├── fixtures/
│   └── ...
├── pyproject.toml
└── README.md
```

### Key Components

- **Models** - Normalized job schema and configuration data classes
- **Config** - YAML-based configuration loading and validation
- **Database** - SQLite persistence layer
- **Collectors** - Platform-specific job scrapers (Greenhouse, Lever, Ashby, JSON-LD)
- **Normalization** - Text processing and hash functions
- **Deduplication** - Cross-source duplicate detection
- **Reporting** - JSON and Markdown report generation
- **Email** - SMTP delivery of reports
- **CLI** - Command-line interface for local and automated operations

## Adding a Company

1. Verify the company's source exists and is accessible
2. Determine source type (greenhouse, lever, ashby, or jsonld)
3. Get the source identifier (board token, site URL, etc.)
4. Add to `config/companies.yaml`:

```yaml
  - id: my-company
    name: My Company
    enabled: true
    priority: high
    categories:
      - software
    locations:
      - Austin, TX
    sources:
      - type: greenhouse
        board_token: mycompany
```

5. Initialize database to register source
6. Test with: `python -m job_collector collect --company my-company --dry-run`

## Adding a New Collector

To support a new ATS platform:

1. Create `src/job_collector/collectors/newplatform.py`
2. Implement `JobCollector` interface:
   - Constructor with company ID and source config
   - `async def collect() -> CollectionResult` method
3. Add tests in `tests/test_newplatform.py`
4. Register in `config.py` source type validation
5. Document in README

## Troubleshooting

### Source Collection Fails

Check the database for last error:
```bash
sqlite3 data/jobs.db "SELECT * FROM sources WHERE id LIKE '%failing-source%';"
```

Verify credentials and board tokens:
- Greenhouse: Visit `company.greenhouse.io` and look for board ID
- Lever: Check `company.lever.co`
- Ashby: Check `company.ashby.co`

### No Jobs Collected

1. Verify companies are enabled in config
2. Check that sources have valid identifiers
3. Run with `--log-level DEBUG` for detailed output
4. Test search rules match job titles

### Email Not Sending

1. Verify SMTP credentials in GitHub secrets
2. Check that Gmail app passwords are generated (not account password)
3. Review workflow logs for SMTP errors
4. Ensure `JOB_EMAIL_FROM` matches the SMTP username

### Database Locked

SQLite may lock if multiple processes access it simultaneously. The workflow uses concurrency controls to prevent this. Locally, ensure you're not running collection and reports at the same time.

## Security and Privacy

### Credentials

- All credentials stored only in GitHub Actions secrets
- Never commit passwords, tokens, or API keys
- Use environment variables for sensitive configuration
- Email attachments do not contain full job details or credentials

### Data Handling

- Job descriptions treated as untrusted text
- HTML sanitized before text conversion
- No execution of scripts or tracking pixels from career pages
- SQL injection prevention via parameterized queries
- Sensitive personal information (SSNs, etc.) never stored

### Rate Limiting

- Configurable timeouts per source (default 30 seconds)
- Backoff for transient failures
- Respect of published access restrictions
- Identifiable user agent

## Limitations (First Release)

- Does not automate job applications
- Does not contact employers
- Does not scrape Indeed or Craigslist
- No web dashboard (reports via email)
- No pull request automation
- No Workday or government job systems
- No user feedback integration

These are planned for future releases when demand is validated.

## Future Enhancements

- Workday and government job system support
- Next.js review dashboard
- Application status tracking
- User feedback and ranking adjustments
- Support for multiple candidates
- LLM-assisted job evaluation
- Supabase persistence option

## Contributing

This is a personal project for Christopher Barreras. External contributions are not currently accepted, but feel free to fork and adapt for your own use.

## License

MIT
