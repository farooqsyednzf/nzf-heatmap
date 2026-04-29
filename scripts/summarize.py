"""LLM-powered case summary generation. One sentence, fully anonymized.

Called only for NEW cases during reconciliation - never re-summarizes existing.
Includes a regex leak-detector safety net before any summary leaves this module.
"""
import os
import re

from anthropic import Anthropic

from . import config


SYSTEM_PROMPT = """You are writing one-sentence case descriptions for a public charity heat map. Each summary must be:

- Fully anonymized: NO names, NO suburbs/cities, NO employer names, NO identifying details
- Written in third person using a role: Brother, Sister, Mother, Father, Student, Single mother, Single father, Refugee family, Elderly applicant. Use "Applicant" only as a last resort. NEVER use "Individual".
- Convey both the cause of need AND the risk/impact of not helping
- Short, factual, with appropriate emotional weight - never sensationalized
- One sentence only, ending with a period

Examples of correct output:
- Sister escaping difficult circumstances requiring rental assistance, risking homelessness.
- Father asking for help with funeral costs, unable to bury his daughter without support.
- Single Mother asking for help with bills, unable to afford food for her children.
- Refugee family newly arrived requiring emergency relief, unable to cover basic essentials.
- Elderly applicant requires medical treatment costs, risking deterioration of their health.

Output ONLY the one-sentence summary. No preamble, no quotes, no explanation, no markdown."""


# Quick regex tripwires for content that should never reach a public site
_LEAK_PATTERNS = [
    re.compile(r"\b04\d{2}\s?\d{3}\s?\d{3}\b"),                   # AU mobile
    re.compile(r"\b\d{2}\s?\d{4}\s?\d{4}\b"),                     # AU landline
    re.compile(r"\S+@\S+\.\S+"),                                  # email
    re.compile(r"\b\d+\s+[A-Z][a-zA-Z]+\s+(Street|Road|Lane|Avenue|St|Rd|Ave|Dr|Drive|Cres)\b"),
]


def has_potential_leak(summary: str) -> bool:
    return any(p.search(summary) for p in _LEAK_PATTERNS)


def _client() -> Anthropic:
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def generate_summary(description: str, model: str | None = None) -> str:
    """Raw generator. Use generate_summary_safe() in pipeline code."""
    if not description or not description.strip():
        return config.SUMMARY_FALLBACK

    msg = _client().messages.create(
        model=model or config.ANTHROPIC_MODEL,
        max_tokens=config.ANTHROPIC_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Generate a one-sentence summary for this case:\n\n{description}",
        }],
    )
    text = msg.content[0].text.strip().strip('"').strip("'")
    if text and not text.endswith("."):
        text += "."
    return text


def generate_summary_safe(description: str, model: str | None = None) -> str:
    """Generator with two safety nets:
       1. Catches API errors and falls back to generic summary.
       2. Scans output for PII patterns; if anything matches, returns generic.
    """
    try:
        summary = generate_summary(description, model)
    except Exception as e:
        print(f"[summarize] API error → using fallback: {e}")
        return config.SUMMARY_FALLBACK

    if has_potential_leak(summary):
        print(f"[summarize] leak detected → using fallback. Original: {summary!r}")
        return config.SUMMARY_FALLBACK

    return summary
