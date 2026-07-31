# Source Validation Guide

This guide explains how to discover the underlying ATS for each company and enable them in the job collector.

## Before You Start

1. Read `job_source_registry_instructions.md` for the complete employer list and validation criteria
2. Start with the **Recommended First Activation Set** (20 companies listed in the registry)
3. Validate each source BEFORE setting `enabled: true`
4. Only enable sources that have been successfully tested

## Discovery Procedure

### Step 1: Identify the ATS Type

Visit the company's careers URL and determine what platform powers it. Look for:

**Greenhouse** (most common)
- URL contains `/boards/` or `/jobs`
- Page header says "Powered by Greenhouse"
- URL pattern: `https://boards.greenhouse.io/companyname/jobs`
- Board token is the company identifier after `/boards/`

**Lever**
- URL contains `jobs.lever.co`
- Page layout is Lever's standard design
- URL pattern: `https://jobs.lever.co/companyname`
- Board name is the company identifier in the URL

**Ashby**
- URL contains `jobs.ashby.co` or `careers.ashby.co`
- Page shows Ashby branding
- URL pattern: `https://jobs.ashby.co/companyname`
- Organization name is the identifier in the URL

**JSON-LD (Generic Career Pages)**
- View page source (Ctrl+U / Cmd+U)
- Search for `<script type="application/ld+json">`
- Look for `"@type": "JobPosting"`
- Use the full careers page URL

**Workday** (University, Government, Large Enterprise)
- URL contains `myworkdayjobs.com`
- Custom parsing may be needed
- Currently supported via JSON-LD fallback

### Step 2: Test Access

Open the careers page in your browser:

1. Does it load without JavaScript rendering? ✓
2. Can you see job listings? ✓
3. Is there pagination or a "load more" button? Note this
4. Can you filter by location? Note the URL parameter

### Step 3: Extract the Source Identifier

#### For Greenhouse:

1. Open the careers page
2. Look at the URL: `https://boards.greenhouse.io/BOARDTOKEN/jobs`
3. The `BOARDTOKEN` is your identifier
4. Example: `https://boards.greenhouse.io/sailpoint/jobs` → `board_token: sailpoint`

#### For Lever:

1. Open the careers page
2. Look at the URL: `https://jobs.lever.co/BOARDNAME`
3. The `BOARDNAME` is your identifier
4. Example: `https://jobs.lever.co/cirruslogic` → `board_name: cirruslogic`

#### For Ashby:

1. Open the careers page
2. Look at the URL: `https://jobs.ashby.co/ORGNAME`
3. The `ORGNAME` is your identifier
4. Example: `https://jobs.ashby.co/samsung` → `board_name: samsung`

#### For JSON-LD:

1. Use the full careers page URL
2. Example: `https://www.q2.com/company/careers` → `site_url: https://www.q2.com/company/careers`

### Step 4: Update Configuration

Edit `config/companies.yaml` and add the source identifier:

**Greenhouse Example:**
```yaml
  - id: q2-holdings
    name: Q2 Holdings
    enabled: false  # Keep disabled until validated
    sources:
      - type: greenhouse
        board_token: q2  # Add your discovered token
```

**Lever Example:**
```yaml
  - id: sailpoint
    name: SailPoint
    enabled: false
    sources:
      - type: lever
        board_name: sailpoint  # Add your discovered name
```

**Ashby Example:**
```yaml
  - id: samsung-austin
    name: Samsung Austin
    enabled: false
    sources:
      - type: ashby
        board_name: samsung  # Add your discovered name
```

**JSON-LD Example:**
```yaml
  - id: q2-holdings
    name: Q2 Holdings
    enabled: false
    sources:
      - type: jsonld
        site_url: https://www.q2.com/company/careers  # Full URL
```

### Step 5: Test Collection

Run a test collection for this one company:

```bash
# Validate config
python -m job_collector validate-config

# Initialize database
python -m job_collector init-db

# Collect from specific company (dry run)
python -m job_collector collect --company q2-holdings --dry-run
```

### Step 6: Check Results

Look for:

1. **Success**: "Collection complete: X jobs" ✓
2. **Parsed correctly**: Job titles, locations, apply URLs are present ✓
3. **No duplicates**: Same job appears only once ✓
4. **Stable IDs**: Job IDs don't change on retry ✓
5. **Reasonable pagination**: No errors about rate limits ✓

### Step 7: Enable and Commit

If the test succeeds:

```yaml
enabled: true  # Change from false to true
```

Then commit to git:

```bash
git add config/companies.yaml
git commit -m "Enable Q2 Holdings (Greenhouse source)"
```

## Common Issues and Solutions

### Issue: "Connection timeout"

**Cause**: Site is slow or blocking automated requests

**Solution**:
```yaml
sources:
  - type: greenhouse
    board_token: company
    timeout_seconds: 60  # Increase from default 30
```

### Issue: "404 Not Found"

**Cause**: Wrong source identifier or URL

**Solution**:
- Verify the URL in browser manually
- Double-check the board token/name in the URL
- Some companies use custom domains that redirect to their ATS

### Issue: "No jobs returned"

**Cause**: Source might have no active postings, or requires pagination

**Solution**:
- Check the careers page in browser - is there a job listing?
- Try different locations or job categories
- If there are jobs visible but collector finds none, the parser may need adjustment

### Issue: "Large number of duplicates"

**Cause**: Same job posting appears across multiple locations or departments

**Solution**:
- This is expected and normal
- The deduplication logic will suppress exact matches
- Cross-source duplicates will be annotated
- If the same job appears multiple times from the SAME source, there may be a parser issue

## Validation Checklist

Before enabling a source, verify:

- [ ] Career URL is accessible without JavaScript
- [ ] ATS type has been identified
- [ ] Source identifier has been discovered
- [ ] Dry-run collection completes without errors
- [ ] At least one job is returned
- [ ] Job data is parsed correctly
- [ ] Titles, locations, and URLs look reasonable
- [ ] No "known access restrictions" apply
- [ ] robots.txt allows crawling (check with `curl https://example.com/robots.txt`)
- [ ] There's no "please do not automate" notice on the careers page

## Priority Order for Validation

Start with this order (likely to succeed):

1. **Greenhouse sources** - Well-documented, stable API
   - Q2 Holdings, SailPoint, Silicon Labs, Cirrus Logic
2. **Lever sources** - Public API, reliable
   - Salesforce, Adobe, etc. (check which use Lever)
3. **Ashby sources** - Emerging, reliable
   - Various tech companies
4. **JSON-LD sources** - Fallback for others
   - Apple, Dell, IBM (have public job pages)
5. **Workday sources** - Complex, requires custom parsing
   - University of Texas, City of Austin, State of Texas

## Recording Your Findings

As you validate each source, record:

```yaml
company: Q2 Holdings
careers_url: https://www.q2.com/company/careers
ats_type: unknown  # or: greenhouse, lever, ashby, jsonld, workday, custom
board_token: null  # if Greenhouse
board_name: null   # if Lever/Ashby
site_url: https://www.q2.com/company/careers  # if JSON-LD
verified_date: 2026-07-30
test_result: success  # or: failed, blocked, js-required
jobs_found: 5
notes: "Uses [underlying ATS], stable parsing"
```

This helps future validation and when recommending sources to others.

## Security Considerations

- Never commit credentials or API keys
- Use timeouts to prevent hanging requests
- Respect rate limits and robots.txt
- Use honest user-agent identification
- Don't automate login-protected sites
- Don't bypass CAPTCHA
- Report actual errors (timeout, 429 rate limit, etc.)

## Next Steps

After validating 5-10 sources successfully:

1. Enable them in GitHub
2. Configure email secrets
3. Run the GitHub Actions workflow
4. Review the daily reports for 1 week
5. Then expand to more sources gradually
