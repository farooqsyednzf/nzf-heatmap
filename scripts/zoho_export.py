"""Pull cases from Zoho Analytics via the Bulk Data Export API v2.

Flow:
  1. Exchange refresh token for short-lived access token.
  2. Submit SQL export job. Get jobId.
  3. Poll until jobCode signals completion.
  4. Download CSV. Parse with DictReader (preserves case_id as string).
"""
import csv
import io
import json
import os
import time
from typing import Dict, List

import requests

from . import config


# ── Auth ──────────────────────────────────────────────────────────────────────
def get_access_token() -> str:
    """Exchange refresh token for short-lived access token (~1hr lifetime)."""
    url = f"{config.ZOHO_ACCOUNTS_URL}/oauth/v2/token"
    params = {
        "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"],
        "client_id":     os.environ["ZOHO_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CLIENT_SECRET"],
        "grant_type":    "refresh_token",
    }
    r = requests.post(url, params=params, timeout=30)
    r.raise_for_status()
    body = r.json()
    if "access_token" not in body:
        raise RuntimeError(f"Zoho token exchange failed: {body}")
    return body["access_token"]


def _headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization":     f"Zoho-oauthtoken {access_token}",
        "ZANALYTICS-ORGID":  config.ZOHO_ORG_ID,
    }


# ── Bulk export ───────────────────────────────────────────────────────────────
def _raise_with_body(r: requests.Response, context: str) -> None:
    """Like raise_for_status(), but prints Zoho's error body so we can see WHY."""
    if r.ok:
        return
    print(f"[zoho] HTTP {r.status_code} from {context}")
    try:
        print(f"[zoho] response: {r.json()}")
    except Exception:
        print(f"[zoho] response (raw): {r.text[:500]}")
    r.raise_for_status()


def create_export_job(access_token: str) -> str:
    """Submit SQL export job. Returns jobId.

    Note: Zoho uses GET for this despite it being a write op, and CONFIG
    goes in the URL query string (not form-encoded body).
    """
    url = (
        f"{config.ZOHO_ANALYTICS_URL}/restapi/v2/bulk/workspaces/"
        f"{config.ZOHO_WORKSPACE_ID}/data"
    )
    cfg = json.dumps({
        "responseFormat": "csv",
        "sqlQuery":       f'SELECT * FROM "{config.ZOHO_VIEW_NAME}"',
    })
    r = requests.get(
        url,
        headers=_headers(access_token),
        params={"CONFIG": cfg},
        timeout=60,
    )
    _raise_with_body(r, "create_export_job")
    body = r.json()
    job_id = (body.get("data") or {}).get("jobId")
    if not job_id:
        raise RuntimeError(f"No jobId in Zoho response: {body}")
    return job_id


def _job_state(data: dict) -> str:
    """Normalize Zoho job status to one of: complete, in_progress, failed, not_found, unknown.

    Defensive parser - handles both numeric codes (1001-1005) and string descriptions.
    """
    code = str(data.get("jobCode", "")).upper()
    desc = str(data.get("jobStatus", "")).upper()
    blob = f"{code} {desc}"
    if "1004" in blob or "COMPLETE" in blob:
        return "complete"
    if "1003" in blob or "FAILURE" in blob or "ERROR" in blob:
        return "failed"
    if "1005" in blob or "NOT EXIST" in blob or "NOT FOUND" in blob:
        return "not_found"
    if "1001" in blob or "1002" in blob or "PROGRESS" in blob or "QUEUE" in blob:
        return "in_progress"
    return "unknown"


def poll_export_job(access_token: str, job_id: str) -> None:
    """Block until job completes. Raises on error or timeout."""
    url = (
        f"{config.ZOHO_ANALYTICS_URL}/restapi/v2/bulk/workspaces/"
        f"{config.ZOHO_WORKSPACE_ID}/exportjobs/{job_id}"
    )
    for _ in range(config.EXPORT_POLL_MAX_TRIES):
        r = requests.get(url, headers=_headers(access_token), timeout=30)
        _raise_with_body(r, "poll_export_job")
        data = (r.json() or {}).get("data") or {}
        state = _job_state(data)
        if state == "complete":
            return
        if state in ("failed", "not_found"):
            raise RuntimeError(f"Zoho export job {job_id} {state}: {data}")
        # in_progress or unknown → keep polling
        time.sleep(config.EXPORT_POLL_INTERVAL_S)
    raise TimeoutError(
        f"Zoho export job {job_id} did not complete after "
        f"{config.EXPORT_POLL_INTERVAL_S * config.EXPORT_POLL_MAX_TRIES}s"
    )


def download_export(access_token: str, job_id: str) -> str:
    """Download CSV data. Returns CSV text."""
    url = (
        f"{config.ZOHO_ANALYTICS_URL}/restapi/v2/bulk/workspaces/"
        f"{config.ZOHO_WORKSPACE_ID}/exportjobs/{job_id}/data"
    )
    r = requests.get(url, headers=_headers(access_token), timeout=180)
    _raise_with_body(r, "download_export")
    return r.text


# ── Parsing & normalization ───────────────────────────────────────────────────
def parse_csv(csv_text: str) -> List[Dict[str, str]]:
    """Parse CSV. csv.DictReader returns strings natively - never coerce case_id."""
    reader = csv.DictReader(io.StringIO(csv_text))
    return [dict(row) for row in reader]


def normalize(row: Dict[str, str]) -> Dict[str, str]:
    """Map Zoho column names to canonical pipeline field names. case_id stays a string."""
    return {
        "case_id":      str(row.get("case_id", "")).strip(),
        "client_id":    str(row.get("client_id", "")).strip(),
        "suburb":       str(row.get("cl.Mailing City", "")).strip(),
        "state":        str(row.get("state", "")).strip(),
        "country":      str(row.get("cl.Mailing Country", "")).strip(),
        "postcode":     str(row.get("cl.Mailing Zip", "")).strip(),
        "stage":        str(row.get("cs.Stage", "")).strip(),
        "description":  str(row.get("cs.Description", "")).strip(),
        "created_date": str(row.get("created_date", "")).strip(),
    }


# ── Top-level entry ───────────────────────────────────────────────────────────
def fetch_cases() -> List[Dict[str, str]]:
    """Pull → poll → download → parse → normalize. Returns canonical dicts."""
    print("[zoho] authenticating...")
    token = get_access_token()
    print("[zoho] submitting export job...")
    job_id = create_export_job(token)
    print(f"[zoho] job submitted: {job_id}")
    print("[zoho] polling for completion...")
    poll_export_job(token, job_id)
    print("[zoho] downloading data...")
    csv_text = download_export(token, job_id)
    raw_rows = parse_csv(csv_text)
    rows = [normalize(r) for r in raw_rows]
    print(f"[zoho] fetched {len(rows)} rows")
    return rows
