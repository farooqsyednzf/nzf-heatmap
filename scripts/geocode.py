"""Postcode → lat/lng/suburb/state lookup using pgeocode (offline AU dataset).

Returns both `suburb` (the joined canonical name string from pgeocode, for
back-compat) and `suburbs` (list of canonical suburbs for that postcode, used
to validate Zoho-supplied suburb names against reality).
"""
from typing import Dict, List, Optional

import pgeocode

_nomi = None


def _get_nomi():
    global _nomi
    if _nomi is None:
        _nomi = pgeocode.Nominatim("AU")
    return _nomi


def _split_suburbs(joined: str) -> List[str]:
    """pgeocode joins multiple suburbs as 'Oak Park, Glenroy, Hadfield'.
    Split back into a clean list."""
    if not joined:
        return []
    parts = [p.strip() for p in joined.split(",")]
    return [p for p in parts if p]


def lookup_postcode(postcode: str) -> Optional[Dict]:
    """Returns {lat, lng, suburb, suburbs, state} or None if not resolvable."""
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

    place_name = (
        str(info["place_name"]) if info["place_name"] == info["place_name"] else ""
    )
    state_code = (
        str(info["state_code"]) if info["state_code"] == info["state_code"] else ""
    )

    return {
        "lat":     lat,
        "lng":     lng,
        "suburb":  place_name,                  # joined name (back-compat)
        "suburbs": _split_suburbs(place_name),  # validated list (new)
        "state":   state_code,
    }
