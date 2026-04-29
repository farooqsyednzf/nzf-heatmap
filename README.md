# NZF Australia — Application Heatmap

Public-facing heatmap embedded on [nzf.org.au/local-need](https://nzf.org.au/local-need), showing aggregated zakat application demand across Australia.

## Architecture

```
Zoho CRM (source of truth)
    │
    ▼
GitHub Actions (daily 17:00 UTC ≈ 03:00 AEST)
  ├─ Pulls from Zoho Analytics
  ├─ Filters DV cases
  ├─ Reconciles vs private/master.json
  ├─ LLM-summarizes only NEW cases (Anthropic API)
  ├─ Validates output (schema + AU bbox + PII scan)
  └─ Commits master.json + public/data/*.json
    │
    ▼
Netlify auto-deploys → CDN serves public/
    │
    ▼
nzf.org.au/local-need (iframe embed)
```

**Zero credentials in the browser.** All API tokens live in GitHub Secrets and are only accessed inside the Action runner. The public site receives a single pre-aggregated JSON file (postcodes with anonymized case summaries; no CaseIDs, no Stages, no PII).

## Repo layout

```
.
├── .github/workflows/refresh-data.yml   # daily cron + manual trigger
├── scripts/
│   ├── config.py            # IDs, paths, model settings
│   ├── zoho_export.py       # OAuth + Bulk export API
│   ├── transform.py         # DV filter, status map, tag rules, dates
│   ├── summarize.py         # Anthropic API + leak detector
│   ├── geocode.py           # postcode → lat/lng via pgeocode
│   ├── reconcile.py         # master.json load/save/diff
│   ├── validate.py          # schema + AU bbox + PII scan
│   ├── seed_master.py       # one-off: seed master from a CSV (optional)
│   └── main.py              # orchestrator (entry point)
├── private/
│   └── master.json          # full state, NOT published by Netlify
├── public/                  # Netlify publish dir
│   ├── index.html           # the map (placeholder for now — phase 2)
│   └── data/
│       ├── heatmap.json     # public payload
│       └── meta.json        # last-updated info
├── netlify.toml             # publish dir + CSP + cache headers
├── requirements.txt
└── README.md
```

## GitHub Secrets required

| Secret | Purpose |
|---|---|
| `ZOHO_CLIENT_ID`     | Zoho OAuth client ID |
| `ZOHO_CLIENT_SECRET` | Zoho OAuth client secret |
| `ZOHO_REFRESH_TOKEN` | Long-lived refresh token (scope: `ZohoAnalytics.data.read`) |
| `ANTHROPIC_API_KEY`  | For LLM summary generation on new cases |
| `SLACK_WEBHOOK_URL`  | *(optional)* Posts a message if a daily run fails |

`ZOHO_DC` is set to `com` in the workflow; if your Zoho account ever moves data center, change it there.

## First run

The first run is a clean backfill: every case in Zoho will be summarized fresh by the LLM. Expect ~45–60 minutes wall-clock (Anthropic Tier 1 rate-limited) and ~$8–12 in API costs for ~2,500 cases.

1. **Connect Netlify.** In Netlify: **Add new site → Import from Git → select `nzf-heatmap` repo**. Netlify reads `netlify.toml` and serves `public/`. Note the deploy URL.
2. **Trigger the workflow.** GitHub → **Actions** tab → **Refresh heatmap data** → **Run workflow**. Watch the log; the `[summarize]` lines tick by every ~30–60 seconds.
3. **First commit lands.** Once it completes, `private/master.json`, `public/data/heatmap.json`, and `public/data/meta.json` are committed automatically. Netlify rebuilds.
4. **Embed on nzf.org.au.** Add an `<iframe>` on `/local-need` pointing at the Netlify URL. CSP in `netlify.toml` is already configured to allow this specific origin.

If the first run fails partway through (timeout, transient API error), no master is committed and a re-run starts cleanly from scratch.

## Daily operation

The cron runs at **17:00 UTC daily** (= 03:00 AEST / 04:00 AEDT). Manual runs are available any time via Actions → Run workflow.

Each run is idempotent: if Zoho returned the same data, no commit happens, no Netlify rebuild triggers, no LLM tokens consumed.

## Cost expectations

- **Anthropic API (Sonnet 4.6):** First run ~$8–12 one-off. Daily steady state ~10–50 new cases × ~$0.003 = **<$10/month**. Override `ANTHROPIC_MODEL` env var to `claude-haiku-4-5-20251001` for ~80% cost savings if needed.
- **GitHub Actions:** Free for public repos. For private repos, ~2 minutes/day × 30 days ≈ 60 minutes (free tier covers 2,000/month).
- **Netlify:** Free tier covers hundreds of deploys/month.
- **Zoho:** No additional cost (uses existing CRM Analytics workspace).

## Optional: seeding from an existing CSV

If you ever need to bootstrap or restore `master.json` from a CSV export (e.g. a Coda backup or a manual fix):

```bash
python -m scripts.seed_master path/to/master_export.csv
git add private/master.json
git commit -m "seed: restore master from CSV"
```

The CSV must have columns: `CaseID, Stage, Status, Postcode, Suburb, State, Summary, Tags, CaseDate, Type`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Zoho token exchange failed` | Refresh token expired or wrong DC | Regenerate refresh token; verify `ZOHO_DC=com` |
| `did not complete after 300s` | Zoho export job stuck | Re-run; if persistent, check Zoho Analytics service status |
| `[summarize] API error` | Anthropic key revoked / spend cap hit | Check console.anthropic.com |
| `outside AU range` | Bad geocode for a foreign postcode | Filter at extract level if recurring |
| Heatmap shows old data | Netlify not redeployed | Check Netlify deploy log; verify it's connected to `main` |

## Critical: CaseID handling

`case_id` from Zoho is a large numeric identifier that **must be treated as a string at every stage**. Coercing to int truncates trailing zeros and corrupts the ID. The codebase enforces this via `csv.DictReader` (returns strings) and explicit `str()` casts on read. Don't modify those without thinking it through.
