# Project Status and Handoff

**Last updated:** 2026-08-08

This document supersedes the source-discovery guidance in `DEPLOYMENT.md`,
`AUTO_DISCOVERY.md`, and `SOURCE_VALIDATION_GUIDE.md`. Read this first.

---

## TL;DR

A daily GitHub Action collects jobs from **16 sources** (14 Workday, 2
Greenhouse), filters them to the Austin metro plus Dallas and Starbase, and
emails a **machine-readable feed** to a downstream consumer (ChatGPT) that does
the categorisation and shortlisting.

Current state: **1,697 jobs, 16/16 sources succeeding, 171 tests passing.**
Runs unattended at 07:00 UTC daily.

The division of labour matters: **this system is ETL, not judgment.** It
collects, normalises and delivers. Relevance scoring, seniority judgment and
shortlisting happen downstream. Do not add keyword categorisation that can
*exclude* jobs — over-filtering here silently destroys information the consumer
needs.

---

## Design invariants

These are load-bearing. Each was learned from a production failure; violating
one reintroduces a bug that is hard to spot because it fails silently.

### 1. Identity and location come from the search summary, never the detail fetch

`WorkdayCollector._parse_job` derives `source_job_id` and `location` from the
search summary only. Detail fetches are capped and can fail, so keying off
`detail["jobReqId"]` gave the same posting a different id depending on whether
its detail happened to be fetched. The old id then looked expired and the new
one looked new — 95 UT Austin jobs churned this way every run.

Location follows the same rule because it decides whether the location filter
keeps a posting: if it depended on an optional fetch, jobs would flicker in and
out of the report. `_summary_location()` is used both to pre-filter and to
populate the job, so the two cannot diverge.

### 2. Location filtering happens before detail fetching

Collectors receive a `location_filter` predicate from the orchestrator and apply
it to summaries *first*, so the one-request-per-job detail budget is spent only
on jobs we keep. Previously the cap was exhausted on postings about to be
discarded, which left 13% of kept jobs with no description — Flex lost
descriptions on 106 of 106.

### 3. The email body is the product; the attachment is not

The downstream consumer reads the body. Attachments arrive as
`application/octet-stream` and cannot be opened. Everything the consumer needs
must be in the body, in parseable form.

### 4. Never truncate silently

Gmail clips bodies near 102 KB, dropping records with no indication. The body is
capped by a **byte budget** (`MAX_BODY_BYTES = 90_000`), not a record count, and
always reports `records_included` and `records_omitted` with the reason. The same
rule applies to `max_jobs`, `max_detail_fetches` and search caps: log what was
dropped.

### 5. The city list is the geographic definition

`location_filter.include` in `config/companies.yaml` enumerates places. There is
deliberately **no blanket `Texas` or `, TX` entry** — those matched the whole
state and admitted Starbase (~350 miles away), McGregor and Dallas before anyone
asked for them. Widening the radius means adding a city.

Matching uses word boundaries: plain substring matching made `Buda` (a Texas
suburb) match `Budapest`. `exclude` is checked first and wins, because a bare
`Remote` pattern otherwise kept `Remote (Germany)` and ~170 other international
postings.

### 6. Use `database.connect()` for SQLite

`with sqlite3.connect(...)` manages the transaction but **does not close the
connection**. All 13 original call sites leaked a handle (~3,200 per run) and
held Windows file locks. `database.connect()` commits and closes.

---

## Architecture

```
config/companies.yaml   sources + location filter
        |
        v
JobCollectionOrchestrator (collection.py)
  - builds collectors from COLLECTOR_MAP
  - injects the location predicate
  - runs all sources concurrently
        |
        v
Collectors (collectors/*.py)   Workday | Greenhouse | Lever | Ashby | JSON-LD
  - fetch, pre-filter by location, fetch details, normalise
        |
        v
Location filter (config.LocationFilter)   belt-and-braces second pass
        |
        v
StateManager (state.py)   new / changed / unchanged / expired
        |
        v
JobDatabase (database.py)   SQLite, persisted to the job-search-state branch
        |
        v
ReportGenerator (reporting.py)   JSON + Markdown
EmailDelivery (email_delivery.py)   machine-readable record feed
```

Status detection runs **before** persistence. Saving first would make every job
look like it already existed, so every run would report "0 new jobs".

---

## The email contract

Consumed by an automated reader. Header, then one delimited record per job:

```
=== JOB COLLECTOR REPORT ===
generated_at: 2026-08-08T09:43:00Z
total_active: 1697
new: 17
changed: 2
expired: 9
failed_sources: 0
records_included: 19
records_omitted: 0

JOB
id: q2-holdings#workday|REQ-12676
company: Q2 Holdings
title: Software Engineer in Test
location: Austin, TX
employment_type: full_time
remote: unknown
status: new
posted_date: 2026-07-28
first_seen: 2026-08-07
source: q2-holdings#workday
salary:
apply_url: https://...
description:
<multi-line text, last field so it may span lines>
END JOB
=== END REPORT ===
```

Rules the format depends on:

- Scalars are flattened to one line — a newline in a title would corrupt the
  next field.
- `description` is last and may span lines; a description containing `END JOB`
  is rewritten so it cannot break out of its record.
- Absent values emit empty keys rather than disappearing, so record shape is
  constant.
- Only `new` and `changed` jobs are sent. Unchanged postings are already known
  downstream and would swamp the body.

`total_active`, `new`, `changed` and `expired` are distinct and must stay so —
they were previously conflated, and the summary counts were hardcoded to zero.

---

## Sources: 16 working

| Employer | ATS | Notes |
|---|---|---|
| Q2 Holdings, SailPoint, Silicon Labs, NXP, Intel, Adobe, Thermo Fisher | Workday | Large tenants use `search_terms` to narrow server-side |
| Flex | Workday | Tenant is **`flextronics`**, not `flex` |
| City of Austin | Workday | Tenant also serves **Austin Energy** |
| UT Austin, Austin Community College | Workday | UT names buildings, not cities — see filter notes |
| ERCOT, Capital Metro, Clinical Pathology Labs | Workday | |
| Natera | Greenhouse | board_token `natera` |
| SpaceX | Greenhouse | board_token `spacex`; mostly the Bastrop Starlink factory |

### Workday collector options (`parsing_config`)

| Option | Default | Purpose |
|---|---|---|
| `search_terms` | `[""]` | Narrow large tenants server-side; results merged and de-duplicated |
| `max_jobs` | 1000 | Cap per search term |
| `fetch_descriptions` | `true` | Detail endpoint supplies description + absolute post date |
| `max_detail_fetches` | 1500 | Runaway guard, not a budget — filtering happens first |
| `detail_concurrency` | 3 | Kept low; 16 sources run at once and Workday throttles the aggregate |
| `store_raw` | `false` | Retain raw API payloads |

Page size is fixed at 20 — Workday rejects larger values. Transient 429/5xx are
retried with exponential backoff, jitter and `Retry-After` support.

**Greenhouse ignores `page`/`per_page`** and returns the whole board in one
response. A loop that stopped only on a short page never terminated. Fetch once.

---

## Coverage: 16 of 66 targets

| Status | Count |
|---|---:|
| Working in production | **16** |
| Reachable, not adopted | 2 — Oracle (only 7 Austin jobs), ICU Medical (0) |
| Verified unreachable | 12 |
| Workday, unresolved tenant names | 6 |
| Custom / client-rendered / bot-protected | ~24 |
| Dead URL / DNS | 6 |

### Reachability findings — verified, do not re-litigate

| ATS | Employers | Verdict |
|---|---|---|
| iCIMS | AMD, Arm, TDIndustries, Bergelectric | **AWS WAF captcha** (`x-amzn-waf-action: captcha`). Not circumventable. |
| Eightfold | Applied Materials | AWS WAF captcha |
| Phenom | Cisco, BAE, Ascension, Baylor Scott & White | Client-rendered, no reachable JSON endpoint |
| NeoGov | Travis County, Round Rock | Client-rendered. "0 jobs found" is a pre-JS placeholder — LA City shows it too despite hundreds of openings |
| Taleo | State of Texas | Portal id `101430233` resolves, REST search returns 500 |
| Oracle Cloud | Oracle, ICU Medical | **Works.** `GET /hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={site},limit=25,offset=0` — limit/offset live inside the finder. Host and `CX_*` site are discoverable from the careers page. Not adopted: too few Austin jobs. |

**Dell**: tenant is not `dell` — 30 tenant/site combinations returned nothing.
The other six unresolved Workday tenants look like wrong *names*, not wrong
sites; twelve common site slugs failed against each.

The 2026-08-02 census identified which ATS each employer used but **not whether
its data was retrievable** — that gap produced two wrong recommendations. It
also miscategorised SpaceX as a custom site when it is on Greenhouse, so the
"21 custom" figure was overstated. Verify reachability before planning work.

---

## Known issues and data notes

- **Firefly Aerospace** is on Greenhouse but its board token is not discoverable
  from its careers page; four guesses returned 404.
- **Austin Regional Clinic** (UltiPro) and **Helix Electric** (Taleo) expose no
  board on their landing pages.
- **Thermo Fisher appears twice** in the employer list.
- **IBEW Local 520, Austin Electrical Training Alliance, IEC Central Texas** are
  not job boards — they are union referral halls and apprenticeship programmes
  publishing application *windows*. They need page-change detection, a different
  feature.
- `config/companies_discovered.yaml` is misleading output from the old
  auto-discovery run. Do not use it.
- Running several collections back-to-back exhausts the retry budget and can
  fail every source at once. A once-daily run does not provoke this.

---

## Daily automation

`.github/workflows/collect-jobs.yml` runs at `0 7 * * *` (07:00 UTC = 2 AM
Central). Working as of 2026-08-06: restores state, collects, reports, emails.

- `--config`/`--output` are **top-level** arguments and must precede the
  subcommand; placing them after is an argparse error.
- The test step is `continue-on-error` — a test failure must not stop collection.
- State persists on the `job-search-state` branch. `data/jobs.db` is gitignored,
  so it is force-added; the branch is fetched explicitly before restore.
- Deleting that branch resets state: every job then reports as new once. Do this
  after a change to identity or the location filter, otherwise the next email is
  a confusing mix of phantom expiries and re-keyed duplicates.
- Email needs `JOB_EMAIL_SMTP_USERNAME` (the Gmail account the App Password
  belongs to), `JOB_EMAIL_SMTP_PASSWORD` and `JOB_EMAIL_FROM`. Recipient is
  `JOB_EMAIL_TO`.
- GitHub disables scheduled workflows after 60 days without commits.

---

## Next steps

1. **Watch two clean nightly runs.** Dallas and Starbase were just added, so the
   next email is a large one-off; the run after should be a normal delta.
2. **Optional category metadata** — as *hints only*, never exclusion rules. The
   consumer has explicitly asked not to have jobs filtered by keyword.
3. **Widen the radius** if wanted: McGregor, Houston, San Antonio, Port Aransas
   are one line each in `location_filter.include`.
4. **Browser-based collector**, only if a specific employer justifies it. Viable
   for the client-rendered sites (no bot protection to defeat), but it means a
   Playwright dependency in a workflow that currently runs in under two minutes.
   Worth it for a local employer with frequent entry-level openings; not worth it
   for a global tech company whose postings mostly get filtered out.

**Do not** attempt the WAF-protected sites. That means defeating a CAPTCHA.

---

## Running it

```bash
pip install -e ".[dev]"

python -m job_collector --config config validate-config
python -m job_collector --config config init-db
python -m job_collector --config config collect
python -m job_collector --config config report
python -m job_collector --config config send-email

pytest -q
```

Use `--database <path>` to work against a scratch database instead of
`data/jobs.db`.

Output lands in `output/latest_jobs.json`, `output/latest_report.md`, and dated
copies under `output/archive/`. The database is `data/jobs.db` (gitignored).

### Verifying a change

Collect twice against a fresh database. The second run must report
**0 new, 0 changed, 0 expired**. Anything else means job identity or location is
not deterministic — see invariants 1 and 2.
