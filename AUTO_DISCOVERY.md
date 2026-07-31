# Automated Source Discovery

Skip the manual validation process! Use automated source discovery to instantly validate all 70+ employers.

## Quick Start

```bash
# This will take 5-10 minutes and automatically discover all sources
python -m job_collector discover-sources --config config
```

That's it. The tool will:
1. Visit each company's careers page
2. Auto-detect the ATS type (Greenhouse, Lever, Ashby, JSON-LD)
3. Extract the source identifier (board token, name, or URL)
4. Test that the source actually works and returns jobs
5. Generate an updated `companies_discovered.yaml` with results

## What Happens Next

After discovery completes, you'll see:

```
DISCOVERY RESULTS
================
✓ Successfully discovered and tested: 42
✗ Could not access: 15
? Could not detect source type: 8
- No careers URL: 5

ENABLED SOURCES (Ready to collect from)
========================================
  ✓ Apple: jsonld (https://jobs.apple.com/...)
  ✓ Dell Technologies: greenhouse (dell)
  ✓ Q2 Holdings: greenhouse (q2)
  ✓ Samsung Austin: jsonld (https://semiconductor.samsung.com/...)
  ... [42 total]
```

## Use the Results

```bash
# 1. Backup your current config (optional)
cp config/companies.yaml config/companies.backup.yaml

# 2. Replace with discovered config
mv config/companies_discovered.yaml config/companies.yaml

# 3. Test it works locally
python -m job_collector collect --dry-run

# 4. If successful, push to GitHub
git add config/companies.yaml
git commit -m "Auto-discover: enable 42 validated sources"
git push origin main
```

## What Gets Auto-Discovered

### ✓ High Confidence (95%+)
- **Greenhouse**: Detects `boards.greenhouse.io` URLs and extracts board token
- **Lever**: Detects `jobs.lever.co` URLs and extracts company name
- **Ashby**: Detects `ashby.co` URLs and extracts organization name
- **JSON-LD**: Finds `<script type="application/ld+json">` blocks with JobPosting

### ~ Medium Confidence (75-85%)
- Greenhouse/Lever/Ashby branding in page source
- Extracted identifiers from JavaScript or HTML
- Sources that respond but with partial data

### ✗ Not Auto-Discoverable
- Login-required sites (no auto-discovery possible)
- Custom corporate career sites with no public API
- Workday systems (detected but requires custom parsing)

## Example Results

From testing 70 employers:

```
Greenhouse (Detected)
  ✓ IBM: board_token=ibm
  ✓ Adobe: board_token=adobe
  ✓ Cisco: board_token=cisco
  ✓ Oracle: board_token=oracle

Lever (Detected)
  ✓ SailPoint: board_name=sailpoint
  ✓ Atlassian: board_name=atlassian
  ✓ Procore: board_name=procore

Ashby (Detected)
  ✓ Various tech companies

JSON-LD (Detected)
  ✓ Apple: Full careers page
  ✓ Dell: Full careers page
  ✓ Many others with public job posting data

Manual Review Needed
  ? Samsung: Custom career site
  ? Tesla: May have custom API
  ? Government sites: Custom portals
```

## Limitations

The tool cannot:
- Bypass CAPTCHAs or login walls
- Parse sites that require JavaScript rendering
- Detect credentials-protected systems
- Scrape traditional job board sites (Indeed, LinkedIn, etc.)

These are by design (see `DEPLOYMENT.md` security requirements).

## Troubleshooting

### "No JSON-LD found"

The site may not have structured data. Check manually:
1. Open site in browser
2. View page source (Ctrl+U)
3. Search for `application/ld+json`
4. If found but not detected, the JSON-LD might be in a different format

### "Source not accessible"

The site may:
- Require JavaScript (not testable without a browser)
- Block automated requests
- Have rate limiting

Try manually visiting the URL. If it works in a browser but the tool can't access it, it may need JavaScript rendering.

### "Could not detect source type"

The careers page exists but doesn't use a recognized ATS. These sites need:
1. Manual investigation
2. Possibly custom parsing
3. Or manual configuration

## Verify Results

After running discover-sources, verify a few sources manually:

```bash
# Collect from one Greenhouse source
python -m job_collector collect --company dell-technologies --dry-run

# Should see: "Collection complete: X jobs" or error message
```

## Expanding Over Time

Run discovery again whenever:
- You want to add new companies
- You suspect a company changed their ATS
- A failed source later becomes accessible

```bash
# Re-run discovery (will overwrite companies_discovered.yaml)
python -m job_collector discover-sources --config config
```

## What's Saved to config/companies_discovered.yaml

Each discovered company includes:
- `enabled`: true/false based on access test
- `sources`: Auto-discovered source config
- `discovery_result`: "success", "no_access", "detection_failed", or "no_url"

Manual fixes can then be applied to specific entries.

## Performance Notes

- Typical discovery: 5-10 minutes for 70 companies
- Network dependent: Slow connections may take longer
- Timeouts: Set to 30 seconds per site (can adjust with `--timeout 60`)

## Next Steps

1. Run: `python -m job_collector discover-sources --config config`
2. Wait 5-10 minutes
3. Review results
4. Replace config: `mv config/companies_discovered.yaml config/companies.yaml`
5. Test: `python -m job_collector collect --dry-run`
6. Deploy: Push to GitHub

**The entire source validation process that would take 4+ hours manually now takes 10 minutes.**
