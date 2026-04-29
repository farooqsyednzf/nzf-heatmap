"""LLM-powered case summary generation. One sentence, fully anonymized.

Called only for NEW cases during reconciliation - never re-summarizes existing.
Includes a regex leak-detector safety net before any summary leaves this module.

This version (v2) hardens the output cleaning to prevent Sonnet's internal
reasoning ("Hmm, let me redo this...", "Wait - I should...", retries) from
ending up in the public payload.
"""
import os
import re

from anthropic import Anthropic

from . import config


SYSTEM_PROMPT = """You are writing one-sentence case descriptions for a public charity heat map. Each summary must be:

- Fully anonymized: NO names, NO suburbs/cities, NO countries, NO employer names, NO identifying details
- Written in third person using one of these roles: Brother, Sister, Mother, Father, Single mother, Single father, Student, Refugee family, Elderly applicant, Applicant. All ten are equally acceptable - pick whichever best fits the case. NEVER use "Person", "Individual", "Adult", or other labels not on this list.
- Convey both the cause of need AND the risk/impact of not helping
- Short, factual, with appropriate emotional weight - never sensationalized
- One sentence only, ending with a period

Examples of correct output:
- Sister escaping difficult circumstances requiring rental assistance, risking homelessness.
- Father asking for help with funeral costs, unable to bury his daughter without support.
- Single mother asking for help with bills, unable to afford food for her children.
- Refugee family newly arrived requiring emergency relief, unable to cover basic essentials.
- Elderly applicant requires medical treatment costs, risking deterioration of their health.
- Applicant facing financial hardship requesting emergency assistance, risking inability to meet basic needs.

CRITICAL OUTPUT RULES:
- Output ONLY the final one-sentence summary. Nothing else.
- Do NOT include reasoning, self-corrections, retries, or alternate versions.
- Do NOT write "Hmm,", "Wait,", "Let me redo,", "I should,", "Actually,", or any meta-commentary.
- Do NOT ask for more information. If the case has insufficient detail, write a generic summary using "Applicant".
- Do NOT use newlines. Your entire response is one sentence on one line.
- If your first attempt is wrong, mentally discard it and write only the corrected version. Never show both."""


# Quick regex tripwires for content that should never reach a public site
_LEAK_PATTERNS = [
    re.compile(r"\b04\d{2}\s?\d{3}\s?\d{3}\b"),                   # AU mobile
    re.compile(r"\b\d{2}\s?\d{4}\s?\d{4}\b"),                     # AU landline
    re.compile(r"\S+@\S+\.\S+"),                                  # email
    re.compile(r"\b\d+\s+[A-Z][a-zA-Z]+\s+(Street|Road|Lane|Avenue|St|Rd|Ave|Dr|Drive|Cres)\b"),
]

# Phrases that indicate the model went meta — produced reasoning, retries, or
# requests for clarification rather than a clean summary. Any match → fallback.
# Lowercased for matching against summary.lower().
_META_PHRASES = (
    "let me redo",
    "let me revise",
    "let me try again",
    "let me reconsider",
    "let me redo this",
    "let me apply the rules",
    "let me use",
    "let me fix",
    "let me give you",
    "let me start over",
    "i used \"person\"",
    "i used 'person'",
    "i used person",
    "i need to revise",
    "i need to redo",
    "i need to use",
    "i should follow",
    "i should redo",
    "i'll redo",
    "i'll use",
    "i'll go with",
    "i'll provide",
    "i don't have enough",
    "i do not have enough",
    "please provide",
    "please rewrite",
    "could you provide",
    "could you share",
    "more details about",
    "more context is needed",
    "insufficient information",
    "rephrase using",
    "rephrase to use",
    "rewrite using",
    "rewrite without",
    "reattempt",
    "rethinking",
    "with so little",
    "without more context",
    "as a last resort",
    "approved roles",
    "isn't in the approved",
    "is not in the approved",
    "isn't in your approved",
    "isn't on the list",
    "not on the approved",
    "let me apply",
    "let me redo that",
    "let me redo the",
    "i must not",
    "i must use",
    "i can't use",
    "i cannot use",
    "hmm,",
    "wait —",
    "wait -",
    "wait,",
    "actually,",
    "note:",
    "output:",
    "output (",
    "clean version",
)


def has_potential_leak(summary: str) -> bool:
    """Returns True if the summary appears to contain PII."""
    return any(p.search(summary) for p in _LEAK_PATTERNS)


def is_meta_response(text: str) -> bool:
    """Returns True if the text contains internal reasoning, retries, or
    clarification requests — anything that shouldn't reach the public site."""
    if not text:
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in _META_PHRASES)


def clean_summary(raw: str) -> str:
    """Take whatever the model returned and reduce it to a single clean sentence.

    Strategy: take only the FIRST sentence. The first sentence is what the model
    produced before any second-guessing. If it's clean, we use it. If it itself
    contains meta-commentary, the caller falls back.
    """
    if not raw:
        return ""

    # Trim outer whitespace and stray quote characters that sometimes wrap output
    text = raw.strip().strip('"').strip("'").strip()

    # Cut at the first newline. Anything after a newline is either reasoning,
    # a retry, or a meta-response — none of which we want.
    text = text.split("\n", 1)[0].strip()

    # Take only the first sentence (terminated by . ! or ?). Some good first
    # sentences end with no terminator at all if max_tokens cut them short, so
    # only split if a terminator actually exists.
    match = re.search(r"[.!?]", text)
    if match:
        text = text[: match.end()].strip()

    # Strip stray leading/trailing quotes one more time
    text = text.strip('"').strip("'").strip()

    # Make sure it ends with a period
    if text and not text.endswith((".", "!", "?")):
        text += "."

    return text


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
    raw = msg.content[0].text
    return clean_summary(raw)


def generate_summary_safe(description: str, model: str | None = None) -> str:
    """Generator with three safety nets:
       1. Catches API errors → fallback.
       2. Detects meta-responses (reasoning/retries/clarification asks) → fallback.
       3. Scans for PII patterns → fallback.

    Note: meta-detection runs against the RAW model output (before cleaning)
    because that's where the giveaway phrases live. Cleaning would discard
    them silently, so we'd never know to flag the case.
    """
    if not description or not description.strip():
        return config.SUMMARY_FALLBACK

    try:
        msg = _client().messages.create(
            model=model or config.ANTHROPIC_MODEL,
            max_tokens=config.ANTHROPIC_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Generate a one-sentence summary for this case:\n\n{description}",
            }],
        )
        raw = msg.content[0].text or ""
    except Exception as e:
        print(f"[summarize] API error → using fallback: {e}")
        return config.SUMMARY_FALLBACK

    # Meta-response detection runs against raw output
    if is_meta_response(raw):
        print(f"[summarize] meta-response detected → using fallback. Raw: {raw[:120]!r}")
        return config.SUMMARY_FALLBACK

    summary = clean_summary(raw)

    if not summary:
        print(f"[summarize] empty after cleaning → using fallback. Raw: {raw[:120]!r}")
        return config.SUMMARY_FALLBACK

    if has_potential_leak(summary):
        print(f"[summarize] PII leak detected → using fallback. Original: {summary!r}")
        return config.SUMMARY_FALLBACK

    return summary
