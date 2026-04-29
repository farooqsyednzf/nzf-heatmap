"""Reconcile fresh Zoho extract against master.json state.

master.json is the source of reconciliation truth. It lives in the repo (in
private/, not published) so every state change is a git commit - audit trail
for free.
"""
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Set, Tuple


def load_master(path: str) -> Dict[str, dict]:
    """Load master.json. Returns dict keyed by case_id (string).

    case_id is always cast to str on read - never coerce to int/float, ever.
    """
    if not os.path.exists(path):
        print(f"[reconcile] {path} not found, starting from empty master")
        return {}
    with open(path) as f:
        data = json.load(f)
    cases = data.get("cases", {})
    return {str(k): v for k, v in cases.items()}


def save_master(path: str, cases: Dict[str, dict]) -> None:
    """Atomic write: tmp file → rename. Sorted keys for stable git diffs."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "version": 1,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def diff(
    extract_rows: List[dict],
    master: Dict[str, dict],
) -> Tuple[Set[str], Set[str], Set[str]]:
    """Compute reconciliation deltas.

    Returns:
        new_ids:           in extract, not in master
        stage_changed_ids: in both, but Stage value differs
        removed_ids:       in master, not in extract
    """
    extract_by_id = {r["case_id"]: r for r in extract_rows if r.get("case_id")}
    extract_ids = set(extract_by_id.keys())
    master_ids  = set(master.keys())

    new_ids     = extract_ids - master_ids
    removed_ids = master_ids - extract_ids

    stage_changed_ids: Set[str] = set()
    for cid in extract_ids & master_ids:
        new_stage = (extract_by_id[cid].get("stage") or "").strip()
        old_stage = str(master[cid].get("stage") or "").strip()
        if new_stage != old_stage:
            stage_changed_ids.add(cid)

    return new_ids, stage_changed_ids, removed_ids
