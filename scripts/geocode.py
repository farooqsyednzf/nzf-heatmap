"""Postcode → lat/lng/suburb/state lookup using pgeocode (offline AU dataset)."""
from typing import Dict, Optional

import pgeocode

_nomi = None


def _get_nomi():
    global _nomi
    if _nomi is None:
        _nomi = pgeocode.Nominatim("AU")
    return _nomi


def lookup_postcode(postcode: str) -> Optional[Dict]:
    """Returns {lat, lng, suburb, state} or None if not resolvable."""
    if not postcode:
        return None
    pc = postcode.strip()
    if not pc:
        return None
    # AU postcodes are 4 digits; pad in case leading zero was stripped
    pc = pc.zfill(4)

    info = _get_nomi().query_postal_code(pc)
    if info is None:
        return None
    try:
        lat = float(info["latitude"])
        lng = float(info["longitude"])
    except (ValueError, TypeError, KeyError):
        return None
    # NaN check
    if lat != lat or lng != lng:
        return None

    return {
        "lat":    lat,
        "lng":    lng,
        "suburb": str(info["place_name"]) if info["place_name"] == info["place_name"] else "",
        "state":  str(info["state_code"]) if info["state_code"] == info["state_code"] else "",
    }
