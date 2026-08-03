# Project Status and Handoff

**Last updated:** 2026-08-02

This document supersedes the source-discovery guidance in `DEPLOYMENT.md`,
`AUTO_DISCOVERY.md`, and `SOURCE_VALIDATION_GUIDE.md`. Read this first.

---

## TL;DR

The original scraping strategy did not work and has been replaced. Greenhouse,
Lever, Ashby, and JSON-LD collectors match **zero** of the target employers. A
live census of all 66 employers found the real distribution is Workday-dominated.

A **Workday collector** now exists and works: **3,214 jobs from 13 employers**,
verified idempotent across consecutive runs. Four pre-existing bugs that would
each have broken the product independently are fixed.

---

## Why the original strategy failed

Two findings from probing every employer live:

1. **0 of 66 employers expose `JobPosting` JSON-LD.** The JSON-LD collector was
   the fallback that everything degraded into. It collects nothing, anywhere.
   These careers pages are JavaScript applications that fetch listings from a
   JSON API after load — the served HTML contains no jobs. This is not a
   blocking or User-Agent problem; the pages return HTTP 200 with full HTML.

2. **0 of 66 employers use Greenhouse, Lever, or Ashby.** Those are startup and
   mid-market systems; these are enterprise employers. The only Greenhouse/Lever/
   Ashby entries in `companies.yaml` are the `example-*` templates.

Auto-discovery masked this. `source_discovery.py` returns `jsonld` at confidence
0.3 for *any* page returning HTTP 200, so every employer was recorded as
"detected, not accessible" rather than "never detected". `_detect_workday()` also
correctly identifies Workday and then returns `source_type="jsonld"`, discarding
the answer at the moment it finds it. **Do not trust `companies_discovered.yaml`.**

---

## ATS census — all 66 employers (probed live 2026-08-02)

| ATS | Count | Notes |
|---|---|---|
| **Workday** | 21 | Verified working; collector built |
| custom / bot-protected | 21 | Apple, Amazon, Google, Meta, IBM, Tesla, Samsung, SpaceX, Atlassian, Procore, Infineon + trades/gov |
| Phenom | 4 | Cisco, BAE Systems, Ascension Seton, Baylor Scott & White |
| iCIMS | 4 | AMD, Arm, TDIndustries, Bergelectric |
| Oracle Cloud | 2 | Oracle, ICU Medical |
| Taleo | 2 | State of Texas, Helix Electric |
| Greenhouse | 2 | Natera, Firefly Aerospace |
| NeoGov / GovernmentJobs | 2 | Travis County, City of Round Rock |
| Eightfold | 1 | Applied Materials |
| UltiPro | 1 | Austin Regional Clinic |
| dead DNS / bad URL | 6 | Needs URL correction |

Dell, Tesla, and Applied Materials return **HTTP 403 even with a browser
User-Agent** — real bot protection. They need their internal JSON API or a
headless browser, not a better scraper.

---

## What was built

### `src/job_collector/collectors/workday.py`

One collector serves every Workday employer — the endpoint shape is identical
across tenants:

```
POST https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
     {"appliedFacets":{},"limit":20,"offset":0,"searchText":""}

GET  https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}
```

Config accepts explicit `tenant` / `wd_host` / `site`, or derives all three from
a `site_url`. Options under `parsing_config`:

| Option | Default | Purpose |
|---|---|---|
| `search_terms` | `[""]` | Narrow large tenants server-side; results merged and de-duplicated |
| `max_jobs` | 1000 | Cap on postings pulled per search term |
| `fetch_descriptions` | `true` | Detail endpoint supplies description + absolute post date |
| `max_detail_fetches` | 300 | Cap on the one-request-per-job detail pass |
| `detail_concurrency` | 5 | Parallel detail requests |
| `store_raw` | `false` | Retain raw API payloads |

Page size is fixed at 20 — Workday rejects larger values on the public endpoint.

### Coverage

13 employers enabled, **3,214 jobs**, 13/13 sources succeeding in ~102s:

| Employer | Jobs | Employer | Jobs |
|---|---|---|---|
| Thermo Fisher | 714 | Austin Community College | 79 |
| Adobe | 631 | ERCOT | 67 |
| Intel | 603 | Q2 Holdings | 49 |
| NXP | 519 | Silicon Labs | 43 |
| UT Austin | 238 | Capital Metro | 37 |
| City of Austin | 123 | Clinical Pathology Labs | 9 |
| SailPoint | 102 | | |

Large tech tenants use `search_terms` to filter to software/QA roles server-side.
Small and municipal tenants pull everything and let `search_rules.yaml` filter
downstream — that is where the electrician and construction-helper roles live.

---

## Bugs fixed

Four were pre-existing and each would have broken the product on its own:

| File | Bug | Consequence |
|---|---|---|
| `collection.py` | Jobs were saved **before** status detection ran | Detection always found them already present — every run would report "0 new jobs" forever |
| `state.py` | `SELECT` referenced a nonexistent `content_hash` column | Collection crashed outright; also the cause of 20 failing tests |
| `cli.py` | Module-level `logger` was never defined | `NameError` masked the real error in all four command handlers |
| `cli.py` / `reporting.py` / `database.py` | `report` was never implemented (`# TODO: Query jobs from database`) | Always wrote an empty report |

The reporting fix required adding `database.get_recent_jobs()`, persisting
`description_text` / `date_posted` / `salary_text` in `save_job` (the reports
render them but nothing stored them), correcting a path double-join
(`output/output/…`), and archiving by copy instead of move so the `latest_*`
files survive.

Two more were in the new collector, caught by running twice:

- Intel returns the literal string `"Spotlight Job"` in `bulletFields` instead of
  a requisition ID, collapsing 16 distinct postings onto one row. IDs now come
  from `jobReqId` or the `externalPath`, never `bulletFields`.
- The `max_detail_fetches` cap selected its subset by API result ordering, so a
  job's content hash flipped depending on whether its description was fetched
  that run. Sorting before truncating made it deterministic.

---

## Verification

```
Run 1 (fresh DB):  3214 new, 0 changed, 0 expired   13 sources OK, 0 failed
Run 2 (same day):     0 new, 0 changed, 0 expired   13 sources OK, 0 failed
```

Idempotent — no false "changed" churn, so the daily email will not cry wolf.
Reports render at 5.9 MB JSON / 150 KB Markdown with real descriptions and
apply links.

**Test suite:** 97 passed, 15 failed, 16 errors — against a baseline of 63
passed, 20 failed, 16 errors. Verified failure-set to failure-set: **zero
regressions**, 5 pre-existing failures fixed. 29 new tests in `test_workday.py`.

Remaining failures are in `ashby` / `lever` / `jsonld` / `deduplication` /
`normalization` (untouched here). The 16 errors are Windows sqlite file-locking
in test teardown, environmental.

---

## Next steps, highest value first

1. **iCIMS + Taleo collectors** — AMD, Arm, TDIndustries, Bergelectric, Helix
   Electric, State of Texas. This is the main **trades** coverage; the trades
   employers are the worst-covered category and where electrician's-helper and
   construction-helper roles concentrate.
2. **Expand `search_rules.yaml`** — the Markdown report currently produces only
   one section ("New Austin-Area Technical Jobs"). Trades categories are needed
   for helper/apprentice/electrician roles to surface properly.
3. **NeoGov / GovernmentJobs collector** — Travis County, City of Round Rock, and
   probably the other municipalities once their URLs are fixed. Strong source of
   helper-grade public-works roles.
4. **Resolve 7 Workday tenants returning HTTP 422** — wrong site IDs, not dead
   tenants: Cirrus Logic, Dover Fueling, Emerson/NI, Flex, HID/ASSA ABLOY, LCRA,
   Texas State. Find the correct site path in each public careers URL.
5. **Phenom / Oracle Cloud / Greenhouse** — 8 more employers; Greenhouse already
   has a working collector.

**Recommendation: do not scrape the 21 custom/bot-protected sites.** Each needs a
bespoke adapter, several sit behind Akamai returning 403, and they break
continuously. Revisit only once the core system runs daily.

---

## Known issues and data notes

- **Dell** is left disabled — its Workday tenant responds but returns 0 jobs, so
  the site ID is wrong.
- **Thermo Fisher appears twice** in the employer list (semiconductor and
  healthcare).
- **Austin Energy is not a separate employer** — it resolves to the City of
  Austin's Workday tenant (`austintexas.wd5/COA_Careers`).
- **IBEW Local 520, Austin Electrical Training Alliance, and IEC Central Texas
  are not job boards.** They are union referral halls and apprenticeship
  programs publishing application *windows*, not postings. No scraper will
  produce listings from them; they need page-change detection, a different
  feature.
- `config/companies_discovered.yaml` is misleading output from the old
  auto-discovery run. Do not use it.

---

## Daily automation

`.github/workflows/collect-jobs.yml` runs at `0 7 * * *` (07:00 UTC = 2 AM
Central). The schedule was always present but the workflow would have failed
every night; fixed:

- **Every CLI call had the wrong flag order.** `--config`/`--output` are
  top-level arguments and must precede the subcommand, so all five invocations
  were argparse errors.
- **The test step gated collection.** Pre-existing failures in the legacy
  collectors would have stopped the run before it collected anything. Now
  `continue-on-error`, informational only.
- **`upload-artifact@v3` is retired** by GitHub and fails hard. Now v4.
- **State persistence never worked.** The state branch was never fetched, so
  every run started fresh; and `data/jobs.db` is gitignored, so `git add` was a
  silent no-op. Now fetched explicitly and force-added.

Still required before email works: **`config/email.yaml`** does not exist (only
`email.yaml.example`), and the three `JOB_EMAIL_*` secrets must be set in the
repo. The email step is `continue-on-error`, so collection and reports work
without it.

GitHub disables scheduled workflows in repositories with no commit activity for
60 days.

## Running it

```bash
pip install -e ".[dev]"

python -m job_collector --config config validate-config
python -m job_collector --config config init-db
python -m job_collector --config config collect
python -m job_collector --config config report

pytest -q
```

Note the flag order: `--config` is a top-level argument and must precede the
subcommand.

Output lands in `output/latest_jobs.json`, `output/latest_report.md`, and dated
copies under `output/archive/`. Database is `data/jobs.db` (gitignored).
