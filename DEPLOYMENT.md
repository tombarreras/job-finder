# Deployment Checklist

> **⚠️ Phase 3 (source discovery) is superseded — see [STATUS.md](STATUS.md).**
>
> Auto-discovery does not work, and no target employer publishes JSON-LD. Sources
> are now configured against the Workday CXS API; 13 employers are already
> enabled and verified. Phases 1–2 (GitHub setup, secrets) and 5–9 (testing,
> deploy, scheduling) still apply.

Complete these steps to deploy the job collector to GitHub and begin daily automation.

## Phase 1: GitHub Setup (15 minutes)

### 1. Create GitHub Repository

If you haven't already, create a private repository:

```bash
git remote add origin https://github.com/tombarreras/job-finder.git
git branch -M main
git push -u origin main
```

### 2. Verify Repository Settings

1. Go to https://github.com/tombarreras/job-finder/settings
2. Under "Code and automation" → "Actions" → "General":
   - ✓ Allow all actions and reusable workflows
   - ✓ Read and write permissions for GITHUB_TOKEN
3. Under "Secrets and variables" → "Actions":
   - Proceed to next section

## Phase 2: Configure Secrets (10 minutes)

Add these secrets to GitHub Actions. Go to Settings → Secrets and variables → Actions → "New repository secret":

### Required Secrets

**JOB_EMAIL_SMTP_USERNAME**
- Value: Your Gmail address (e.g., `tombarreras@gmail.com`)
- Purpose: Email account that sends the reports

**JOB_EMAIL_SMTP_PASSWORD**
- Value: Gmail App Password (16 characters, no spaces)
- How to generate:
  1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
  2. Select "Mail" and "Windows Computer"
  3. Google generates a 16-character password
  4. Copy it (remove spaces if any) as the secret value

**JOB_EMAIL_FROM**
- Value: Your Gmail address (e.g., `tombarreras@gmail.com`)
- Purpose: Sender address on emails

## Phase 3: Auto-Discover Source Identifiers (10 minutes)

**NEW**: Use automated discovery instead of manual validation!

```bash
# This will automatically discover all 70+ companies in ~5-10 minutes
python -m job_collector discover-sources --config config
```

The tool will:
- Visit each company's careers page
- Auto-detect the ATS type (Greenhouse, Lever, Ashby, JSON-LD)
- Extract source identifiers automatically
- Test that each source works
- Generate `companies_discovered.yaml` with results

**Result**: ~40-50 sources automatically validated and ready to use.

See `AUTO_DISCOVERY.md` for details.

---

## Phase 3 (Alternative): Manual Validation (2-4 hours)

If you prefer to validate manually, follow the procedure below. Otherwise, skip to Phase 4.

### 1. Start with Priority Sources

Open `SOURCE_VALIDATION_GUIDE.md` and follow the procedure for these 5 sources:

1. **Q2 Holdings**
   - Type: Likely Greenhouse or JSON-LD
   - URL: https://www.q2.com/company/careers
   - Discovery: Check for ATS type

2. **SailPoint**
   - Type: Likely Greenhouse or JSON-LD
   - URL: https://www.sailpoint.com/company/careers
   - Discovery: Check for ATS type

3. **Silicon Labs**
   - Type: Likely Greenhouse or Ashby
   - URL: https://www.silabs.com/about-us/careers
   - Discovery: Check for ATS type

4. **Samsung Austin Semiconductor**
   - Type: Custom page (official job listing)
   - URL: https://semiconductor.samsung.com/sas/work-with-us/job-opportunities/
   - Discovery: Check structure

5. **City of Austin**
   - Type: Likely government system
   - URL: https://www.austincityjobs.org/
   - Discovery: Check for ATS type

### 2. For Each Source

1. Visit the careers URL in your browser
2. Identify the underlying ATS (Greenhouse, Lever, Ashby, JSON-LD, etc.)
3. Extract the source identifier (board_token, board_name, or site_url)
4. Update `config/companies.yaml` with the identifier
5. Test locally with dry-run:
   ```bash
   python -m job_collector collect --company q2-holdings --dry-run
   ```
6. If successful, set `enabled: true` and commit

### 3. Record Your Findings

Keep a list of successful sources:

```markdown
## Validated Sources

- Q2 Holdings: Greenhouse, board_token: q2 ✓
- SailPoint: Greenhouse, board_token: sailpoint ✓
- Silicon Labs: Greenhouse, board_token: silabs ✓
- Samsung Austin: JSON-LD parsing ✓
- City of Austin: Workday system - pending parser
```

## Phase 4: Use Discovered Configuration

If you used auto-discovery:

```bash
# Backup original (optional)
cp config/companies.yaml config/companies.backup.yaml

# Use discovered config
mv config/companies_discovered.yaml config/companies.yaml

# Verify it looks good
head config/companies.yaml
```

Then proceed to testing below.

---

## Phase 5: Local Testing (30 minutes)

### 1. Simulate GitHub Actions Environment

```bash
# Install dependencies
pip install -e ".[dev]"

# Validate config
python -m job_collector validate-config --config config

# Initialize database
python -m job_collector init-db --config config

# Collect from validated sources
python -m job_collector collect --config config

# Generate reports
python -m job_collector report --config config

# Run tests
pytest -v
```

### 2. Check Output

- JSON report: `output/latest_jobs.json`
- Markdown report: `output/latest_report.md`
- Database: `data/jobs.db`

Verify:
- ✓ Reports contain actual jobs
- ✓ No duplicate jobs listed
- ✓ Job titles, URLs, and descriptions look reasonable
- ✓ At least 10 jobs from your validated sources

## Phase 6: Deploy to GitHub (5 minutes)

### 1. Push to GitHub

```bash
git push origin main
```

### 2. Trigger First Workflow

1. Go to https://github.com/tombarreras/job-finder/actions
2. Click "Collect Jobs" workflow
3. Click "Run workflow"
4. Select branch: "main"
5. Click "Run workflow"

### 3. Monitor Execution

1. Wait for workflow to complete (2-5 minutes)
2. Check the logs for:
   - ✓ "Collection complete: X jobs"
   - ✓ No credential leaks in output
   - ✓ Email sent successfully (if email is configured)

### 4. Verify Email

Check `tombarreras@gmail.com` for:
- ✓ Email from your configured sender address
- ✓ Subject: "Christopher Job Collector -- X new jobs"
- ✓ Summary of new/changed/expired jobs
- ✓ JSON attachment with full job data

## Phase 7: Persistence Branch Setup (5 minutes)

After the first successful workflow run:

1. Check that `job-search-state` branch exists:
   ```bash
   git branch -r | grep job-search-state
   ```

2. Verify the persistence strategy is working:
   - Go to the branch on GitHub
   - You should see `data/jobs.db` file
   - This persists across workflow runs

## Phase 8: Expand Source Coverage (1-2 hours)

### 1. Validate Next Batch

Move to the next 5 sources from the registry:

- Apple
- Dell Technologies
- IBM
- Cirrus Logic
- ERCOT

Follow the same procedure as Phase 3.

### 2. Commit and Re-deploy

```bash
git add config/companies.yaml
git commit -m "Enable additional validated sources"
git push origin main
```

Trigger workflow manually again to test new sources.

## Phase 9: Schedule Daily Automation (Already Configured)

The workflow is already scheduled to run daily at **7:00 AM UTC**:

```yaml
schedule:
  - cron: '0 7 * * *'  # 7 AM UTC daily
```

This converts to:
- **11:00 PM PT** (during Pacific daylight saving - March to November)
- **12:00 AM PT** (midnight - during standard time - November to March)
- **Runs 1 hour before ChatGPT review** (currently configured for morning)

No additional setup needed - the workflow runs automatically.

## Monitoring and Maintenance

### Daily Checks

Every morning, check:
1. Email report arrived with new jobs
2. No errors in GitHub Actions logs
3. Job counts are reasonable (not 0, not thousands)

### Weekly Review

Every Friday or Monday:
1. Check GitHub Actions history for failures
2. Review if any sources failed consistently
3. If a source fails 5+ times, investigate or disable it

### Monthly Expansion

After 1-2 weeks of stable operation with 5-10 sources:
1. Validate and enable next batch of 5-10 sources
2. Monitor for issues
3. Gradually expand toward full 50-100 employer list

## Troubleshooting

### Workflow Fails to Run

**Check**:
1. Are secrets configured? (Settings → Secrets and variables)
2. Is the workflow file at `.github/workflows/collect-jobs.yml`?
3. Do you have a `main` branch?

### No Jobs Collected

**Check**:
1. Are sources enabled in `config/companies.yaml`?
2. Run `python -m job_collector collect --dry-run` locally
3. Check `config/companies.yaml` has correct source identifiers
4. View workflow logs for error messages

### Email Not Sending

**Check**:
1. Are email secrets configured correctly?
2. Is sender email a Gmail account with 2FA?
3. Did you generate an App Password (not regular password)?
4. Check workflow logs for SMTP errors

### Database Issues

**Check**:
1. Is `job-search-state` branch persisting? Check GitHub repo branches
2. Run `python -m job_collector init-db` to reset if needed
3. Check `data/.gitkeep` exists

## Next Steps After Deployment

1. **Week 1**: Monitor daily reports, validate 20 sources
2. **Week 2-3**: Expand to 30-50 sources
3. **Month 2**: Target full 70+ employer list
4. **Month 3+**: Refine based on job relevance and ChatGPT feedback

## Documentation References

- **README.md**: Architecture, configuration, local usage
- **job_source_registry_instructions.md**: Complete employer list and validation criteria
- **SOURCE_VALIDATION_GUIDE.md**: Step-by-step source discovery and testing
- **config/companies.yaml**: Current enabled/disabled sources
- **config/search_rules.yaml**: Job categorization rules

## Questions?

Refer to:
1. README.md → Troubleshooting section
2. SOURCE_VALIDATION_GUIDE.md → Common Issues
3. GitHub Actions workflow logs (detailed error messages)
4. Database queries: `sqlite3 data/jobs.db "SELECT * FROM sources;"`

---

**Status**: Ready for deployment

**Last Updated**: 2026-07-30

**Estimated Time to Full Deployment**: 1-2 hours (with auto-discovery) or 4-6 hours (manual validation)
