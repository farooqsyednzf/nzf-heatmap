"""Main pipeline orchestrator. Run from repo root via `python -m scripts.main`.

Steps:
  1. Pull cases from Zoho Analytics
  2. Filter out DV cases
  3. Load master state
  4. Reconcile (new / stage-changed / removed)
  5. Generate summaries + tags for new cases (LLM call only on truly new cases)
  6. Update statuses for stage-changed cases
  7. Drop removed cases
  8. Save master.json (audit trail in git)
  9. Build & validate public heatmap.json
 10. Save public payload + meta.json
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

from . import config, geocode, reconcile, summarize, transform, validate, zoho_export


def _hr():
    print("─" * 64)


def run() -> int:
    print("=" * 64)
    print(f"NZF heatmap refresh — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 64)

    # ── 1. Pull from Zoho ─────────────────────────────────────────────────────
    rows = zoho_export.fetch_cases()

    # ── 2. DV filter ──────────────────────────────────────────────────────────
    pre_dv = len(rows)
    rows = [r for r in rows if not transform.is_dv_case(r["description"])]
    print(f"[dv] removed {pre_dv - len(rows)} cases ({len(rows)} remain)")

    # Drop rows with no case_id (defensive; shouldn't happen)
    rows = [r for r in rows if r.get("case_id")]

    # ── 3. Load master ────────────────────────────────────────────────────────
    master = reconcile.load_master(config.MASTER_PATH)
    print(f"[master] loaded {len(master)} existing cases")

    # ── 4. Diff ───────────────────────────────────────────────────────────────
    new_ids, changed_ids, removed_ids = reconcile.diff(rows, master)
    print(f"[diff] {len(new_ids)} new · "
          f"{len(changed_ids)} stage-changed · "
          f"{len(removed_ids)} removed")
    _hr()

    extract_by_id = {r["case_id"]: r for r in rows}
    new_master: dict = {}

    # ── 5. Carry over existing cases (preserve summary/tags/etc.) ─────────────
    for cid, existing in master.items():
        if cid in removed_ids:
            continue
        rec = dict(existing)
        if cid in changed_ids:
            new_stage = extract_by_id[cid]["stage"]
            rec["stage"] = new_stage
            rec["status"] = transform.map_stage_to_status(new_stage)
        new_master[cid] = rec

    # ── 6. Build records for new cases (LLM call here) ───────────────────────
    if new_ids:
        print(f"[summarize] generating {len(new_ids)} summaries via Anthropic API...")
    for idx, cid in enumerate(sorted(new_ids), start=1):
        row = extract_by_id[cid]

        # Geocode fallback for missing suburb/state
        geo = geocode.lookup_postcode(row["postcode"]) or {}
        suburb = row["suburb"] or geo.get("suburb", "")
        state  = row["state"]  or geo.get("state",  "")

        tags = transform.extract_tags(row["description"]) or ["family hardship"]
        summary = summarize.generate_summary_safe(row["description"])

        new_master[cid] = {
            "case_id":   cid,
            "stage":     row["stage"],
            "status":    transform.map_stage_to_status(row["stage"]),
            "postcode":  row["postcode"],
            "suburb":    suburb,
            "state":     state,
            "summary":   summary,
            "tags":      tags,
            "case_date": transform.normalize_date(row["created_date"]),
            "type":      "Application",
        }
        if idx % 25 == 0:
            print(f"[summarize] {idx}/{len(new_ids)}")
    if new_ids:
        print(f"[summarize] done")

    # ── 7. Save master ────────────────────────────────────────────────────────
    reconcile.save_master(config.MASTER_PATH, new_master)
    print(f"[master] saved {len(new_master)} cases → {config.MASTER_PATH}")
    _hr()

    # ── 8. Build & validate public payload ────────────────────────────────────
    public = build_public_payload(new_master)
    validate.validate_public_payload(public)

    pii_warnings = validate.scan_for_pii(public)
    for w in pii_warnings:
        print(f"[pii-warn] {w}")
    if pii_warnings and os.environ.get("STRICT_PII") == "1":
        raise validate.ValidationError(
            f"{len(pii_warnings)} PII warnings + STRICT_PII=1 → refusing to publish"
        )

    # ── 9. Save public files ──────────────────────────────────────────────────
    save_public(public)
    print(f"[public] wrote {config.PUBLIC_HEATMAP_PATH} "
          f"({len(public['postcodes'])} postcodes, "
          f"{sum(len(p['cases']) for p in public['postcodes'])} cases)")
    _hr()
    print("✓ pipeline complete")
    return 0


def build_public_payload(master: dict) -> dict:
    """Aggregate master state by postcode, attach lat/lng, strip CaseID/Stage."""
    by_pc: dict = defaultdict(list)
    for c in master.values():
        pc = (c.get("postcode") or "").strip()
        if pc:
            by_pc[pc].append(c)

    postcodes = []
    skipped_no_geo = 0
    for pc, cases in by_pc.items():
        geo = geocode.lookup_postcode(pc)
        if not geo:
            skipped_no_geo += 1
            continue
        first = cases[0]
        postcodes.append({
            "pc":    pc,
            "city":  first.get("suburb") or geo["suburb"],
            "state": first.get("state")  or geo["state"],
            "lat":   geo["lat"],
            "lng":   geo["lng"],
            "cases": [
                {
                    "d":       c.get("case_date", ""),
                    "summary": c.get("summary", ""),
                    "tags":    c.get("tags", []),
                    "status":  c.get("status", ""),
                }
                for c in cases
            ],
        })

    if skipped_no_geo:
        print(f"[public] WARN: {skipped_no_geo} postcodes skipped (no geocode match)")

    return {
        "version":      2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "postcodes":    postcodes,
    }


def save_public(payload: dict) -> None:
    os.makedirs(os.path.dirname(config.PUBLIC_HEATMAP_PATH), exist_ok=True)
    with open(config.PUBLIC_HEATMAP_PATH, "w") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    meta = {
        "generated_at":   payload["generated_at"],
        "version":        payload["version"],
        "postcode_count": len(payload["postcodes"]),
        "case_count":     sum(len(p["cases"]) for p in payload["postcodes"]),
    }
    with open(config.PUBLIC_META_PATH, "w") as f:
        json.dump(meta, f, indent=2)


if __name__ == "__main__":
    sys.exit(run())
