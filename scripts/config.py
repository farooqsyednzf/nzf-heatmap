"""Central configuration for the heatmap pipeline.

Hardcoded IDs and pipeline parameters. Secrets come from environment variables.
"""
import os

# ── Zoho Analytics ────────────────────────────────────────────────────────────
ZOHO_DC = os.environ.get("ZOHO_DC", "com")
ZOHO_ORG_ID = "668395719"
ZOHO_WORKSPACE_ID = "1715382000001002475"
ZOHO_VIEW_NAME = "Cases x Clients - Heatmap"

ZOHO_ACCOUNTS_URL = f"https://accounts.zoho.{ZOHO_DC}"
ZOHO_ANALYTICS_URL = f"https://analyticsapi.zoho.{ZOHO_DC}"

# ── Anthropic ─────────────────────────────────────────────────────────────────
# Sonnet handles the empathetic-but-not-sensationalized summary tone better than
# Haiku. Override via env var if you need to drop down for cost (e.g. during a
# very large backfill): ANTHROPIC_MODEL=claude-haiku-4-5-20251001
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
ANTHROPIC_MAX_TOKENS = 200

# ── Paths (relative to repo root) ─────────────────────────────────────────────
MASTER_PATH = "private/master.json"
PUBLIC_HEATMAP_PATH = "public/data/heatmap.json"
PUBLIC_META_PATH = "public/data/meta.json"

# ── Pipeline behaviour ────────────────────────────────────────────────────────
EXPORT_POLL_INTERVAL_S = 5
EXPORT_POLL_MAX_TRIES = 60          # 5 minutes ceiling
SUMMARY_FALLBACK = "Applicant requires assistance for family hardship."
