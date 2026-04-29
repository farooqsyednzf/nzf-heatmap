"""Stage→Status mapping, DV filter, rule-based tag extraction."""
import re
from typing import List


# ── Stage → Status ────────────────────────────────────────────────────────────
_STAGE_TO_STATUS_RAW = {
    "Being Assisted": [
        "Funding", "Ongoing Funding", "Post-Follow-Up",
        "Phase 4: Monitoring & Impact",
    ],
    "Closed - Not Assisted": [
        "Closed - Not Funded", "Closed - NO Response", "Gaza-2023",
    ],
    "Successfully Assisted": ["Closed - Funded"],
    "Under Assessment": [
        "Ready for Allocation", "Ready For Allocation P2", "Allocated",
        "NM Approval", "Interview", "Waiting On Client", "Follow Up",
    ],
    "Pending Review": ["Intake"],
}
STATUS_MAP = {
    stage.lower(): status
    for status, stages in _STAGE_TO_STATUS_RAW.items()
    for stage in stages
}


def map_stage_to_status(stage: str) -> str:
    """Default to 'Closed - Not Assisted' for unmapped stages (safe failure)."""
    return STATUS_MAP.get((stage or "").strip().lower(), "Closed - Not Assisted")


# ── DV filter ─────────────────────────────────────────────────────────────────
_DV_PATTERNS = [
    r"\bdomestic violence\b",
    r"\bfamily violence\b",
    r"\babus\w*\b",                      # abuse, abused, abusive, abuser
    r"\bassault\w*\b",
    r"\bviolence at home\b",
    r"\bviolent (partner|husband|spouse|wife|ex)\b",
    r"\b(physical|sexual|emotional|psychological) abus\w*\b",
]
_DV_RE = re.compile("|".join(_DV_PATTERNS), re.IGNORECASE)


def is_dv_case(description: str) -> bool:
    if not description:
        return False
    return bool(_DV_RE.search(description))


# ── Tag extraction ────────────────────────────────────────────────────────────
# Order matters: specific tags fire first, generic ones last. Max 3 per case.
TAG_RULES = [
    ("rent assistance",      [r"\brent(al|er|ing)?\b", r"\bevict", r"\blandlord", r"\btenanc"]),
    ("food/groceries",       [r"\bfood\b", r"\bgrocer", r"\bhungr", r"\bstarv", r"\bmeals?\b"]),
    ("utilities",            [r"\butilit", r"\belectric", r"\bgas bill", r"\bwater bill",
                              r"\bpower bill", r"\benergy bill"]),
    ("school fees",          [r"\bschool fee", r"\btuition\b"]),
    ("medical",              [r"\bmedical\b", r"\bhospital\b", r"\bdoctor\b", r"\bsurgery\b",
                              r"\btreatment\b", r"\bmedicat", r"\bprescription\b"]),
    ("debt",                 [r"\bdebts?\b", r"\bloans?\b", r"\bcredit card", r"\bowing\b"]),
    ("funeral costs",        [r"\bfuneral", r"\bburial\b", r"\bdeceased\b"]),
    ("job loss",             [r"\bunemploy", r"\bjob loss", r"\blost (his|her|their|my) job",
                              r"\bredundan", r"\bno income"]),
    ("refugee/migrant",      [r"\brefugee", r"\basylum", r"\bmigrant", r"\bnewly arrived",
                              r"\bhumanitarian visa"]),
    ("mental health",        [r"\bmental health", r"\bdepress", r"\banxiety\b", r"\bpsychiatric",
                              r"\bpsychological"]),
    ("single parent",        [r"\bsingle (mother|father|parent|mum|dad)", r"\bsole parent"]),
    ("disability",           [r"\bdisabilit", r"\bdisabled\b", r"\bndis\b", r"\bwheelchair"]),
    ("housing",              [r"\bhomeless", r"\bshelter\b", r"\baccommodation"]),
    ("appliances/household", [r"\bapplianc", r"\bfridge\b", r"\bwashing machine", r"\bfurniture\b"]),
    ("fuel/transport",       [r"\bfuel\b", r"\bpetrol\b", r"\btransport\b", r"\bcar repair"]),
    ("emergency relief",     [r"\bemergenc", r"\burgent\b", r"\bcrisis\b"]),
    ("family hardship",      [r"\bfamily hardship", r"\bstruggling famil", r"\bhardship\b"]),
]
_COMPILED_TAG_RULES = [
    (tag, [re.compile(p, re.IGNORECASE) for p in patterns])
    for tag, patterns in TAG_RULES
]


def extract_tags(description: str, max_tags: int = 3) -> List[str]:
    if not description:
        return []
    tags: List[str] = []
    for tag, patterns in _COMPILED_TAG_RULES:
        if len(tags) >= max_tags:
            break
        if any(p.search(description) for p in patterns):
            tags.append(tag)
    return tags


# ── Date normalization ────────────────────────────────────────────────────────
_DATE_DDMMYYYY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def normalize_date(s: str) -> str:
    """Convert dd/mm/yyyy or yyyy-mm-dd to ISO yyyy-mm-dd. Empty-safe."""
    if not s:
        return ""
    s = s.strip()
    m = _DATE_ISO.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATE_DDMMYYYY.match(s)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return s  # leave malformed values for validate.py to flag
