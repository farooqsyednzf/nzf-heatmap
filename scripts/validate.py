"""Validate the public payload before commit. Stops bad data shipping live."""
import re
from typing import List


REQUIRED_PC_FIELDS   = ("pc", "city", "state", "lat", "lng", "cases")
REQUIRED_CASE_FIELDS = ("d", "summary", "tags", "status")

# AU bounding box (loose) — catches obvious geocoding glitches
AU_LAT_RANGE = (-44.0, -10.0)
AU_LNG_RANGE = (112.0, 154.0)


class ValidationError(Exception):
    pass


def validate_public_payload(payload: dict) -> None:
    """Hard schema validation. Raises ValidationError on first issue."""
    if "postcodes" not in payload:
        raise ValidationError("missing top-level 'postcodes'")
    if not isinstance(payload["postcodes"], list):
        raise ValidationError("'postcodes' must be a list")
    if len(payload["postcodes"]) == 0:
        raise ValidationError("zero postcodes - refusing to publish empty payload")

    for i, pc in enumerate(payload["postcodes"]):
        for f in REQUIRED_PC_FIELDS:
            if f not in pc:
                raise ValidationError(f"postcode index {i}: missing '{f}'")

        if not isinstance(pc["lat"], (int, float)) or not isinstance(pc["lng"], (int, float)):
            raise ValidationError(f"postcode {pc.get('pc')}: lat/lng not numeric")
        if not (AU_LAT_RANGE[0] <= pc["lat"] <= AU_LAT_RANGE[1]):
            raise ValidationError(f"postcode {pc.get('pc')}: lat {pc['lat']} outside AU range")
        if not (AU_LNG_RANGE[0] <= pc["lng"] <= AU_LNG_RANGE[1]):
            raise ValidationError(f"postcode {pc.get('pc')}: lng {pc['lng']} outside AU range")

        if not isinstance(pc["cases"], list) or len(pc["cases"]) == 0:
            raise ValidationError(f"postcode {pc.get('pc')}: empty or invalid 'cases'")

        for j, case in enumerate(pc["cases"]):
            for f in REQUIRED_CASE_FIELDS:
                if f not in case:
                    raise ValidationError(
                        f"postcode {pc.get('pc')} case {j}: missing '{f}'"
                    )


# ── Soft PII scan (warnings, not errors by default) ───────────────────────────
_PII_PATTERNS = [
    (re.compile(r"\S+@\S+\.\S+"),                                "email"),
    (re.compile(r"\b04\d{2}\s?\d{3}\s?\d{3}\b"),                 "mobile_number"),
    (re.compile(r"\b\d+\s+[A-Z][a-zA-Z]+\s+(Street|Road|Lane|Avenue|St|Rd|Ave|Dr|Drive|Cres)\b"),
                                                                 "street_address"),
]


def scan_for_pii(payload: dict) -> List[str]:
    """Return human-readable warnings. Does not raise."""
    warnings: List[str] = []
    for pc in payload.get("postcodes", []):
        for case in pc.get("cases", []):
            summary = case.get("summary", "")
            for pat, label in _PII_PATTERNS:
                if pat.search(summary):
                    warnings.append(
                        f"PC {pc.get('pc')}: possible {label} in summary: {summary[:80]!r}"
                    )
    return warnings
