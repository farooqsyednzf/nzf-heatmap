"""One-off: reset master.json to an empty state so the next pipeline run
treats every case in Zoho as 'new' and re-summarizes them with the patched
summarizer.

Usage (locally, from repo root):
    python -m scripts.reset_master

Then commit the change and trigger the workflow:
    git add private/master.json
    git commit -m "reset master for re-summarization with patched cleaner"
    git push

The next workflow run will see 0 existing cases, mark all ~2,550 as new,
and call the LLM for each — same cost (~$10) and runtime (~75 mins) as
the first run.
"""
import json
from pathlib import Path

EMPTY = {
    "cases": {},
}


def main() -> None:
    path = Path("private/master.json")
    if not path.exists():
        print(f"[reset] {path} doesn't exist — nothing to reset")
        return

    # Read first to report what we're throwing away
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        n = len(existing.get("cases", {}))
        print(f"[reset] current master.json has {n} cases")
    except Exception as e:
        print(f"[reset] could not read existing master ({e}) — will overwrite anyway")

    path.write_text(json.dumps(EMPTY, indent=2), encoding="utf-8")
    print(f"[reset] wrote empty master to {path}")
    print("[reset] next pipeline run will treat all Zoho cases as new")


if __name__ == "__main__":
    main()
