"""ai_narrative.py - the LLM may narrate, never assert report values.

The analysis endpoints pin ``feasibility_score``, ``cost_breakdown`` and
``vastu_compliance`` to the deterministic engines, but ``ai_metadata`` was
passed through verbatim and its ``parameter_reflection`` is rendered as the
report commentary.  A live Groq run produced, in the same payload as a
certified 62.5 score and a Rs 48.40 lakh budget:

    "The standard grade (approx Rs 2,500/sqft) ... base construction cost
     around Rs 5 million"          <- wrong rate, wrong total
    "feasibility_score": "78"      <- an invented score
    "... Zone III ..."             <- the hazard engine says Zone II (0.10)

This module removes those numeric claims from narrative text before it leaves
the server.  The deterministic numbers stay where they belong: in the report's
own fields, which the model cannot touch.  Redactions are disclosed, not
silent.
"""

from __future__ import annotations

import re
from typing import List, Tuple

CURRENCY_CLAIM = re.compile(
    # The token needs a word boundary and at least one digit: without both, the
    # "rs" inside "layers," matched and the sanitizer corrupted ordinary prose.
    r"(?<![A-Za-z])(?:₹|INR|Rs\.?)\s?\d[\d,]*(?:\.\d+)?"
    r"(?:\s*(?:lakh|lakhs|crore|crores|cr|bn|billion|million|m))?",
    re.IGNORECASE,
)
RATE_CLAIM = re.compile(
    r"(?:₹|INR|Rs\.?)?\s?[\d,.]+\s*(?:/|per)\s*(?:sq\.?\s*ft|sqft|square\s*foot|sq\.?\s*m)",
    re.IGNORECASE,
)
SCORE_CLAIM = re.compile(
    r"(?:\b(?:feasibility|suitability|overall)\s+)?\bscore\b(?:\s+of|\s*[:=])?\s*\d{1,3}(?:\s*/\s*100)?"
    r"|\b\d{1,3}\s*/\s*100\b",
    re.IGNORECASE,
)
ZONE_CLAIM = re.compile(r"\bZone\s+(?:I{1,3}|IV|V|VI|[1-6])\b", re.IGNORECASE)

REPLACEMENTS = {
    "rate": "[rate removed - see the certified cost table]",
    "amount": "[amount removed - see the certified cost table]",
    "score": "score [removed - see the certified suitability score]",
    "zone": "[zone removed - see the hazard profile]",
}


def sanitize_narrative(text: str) -> Tuple[str, List[str]]:
    """Return (clean_text, redaction_kinds).

    A claim the report can verify is removed rather than trusted.  Percentages
    are left alone: they are usually description (coverage, slope, void), not
    a report value, and the report's own percentages come from the engines.
    """
    if not text:
        return text, []

    redactions: List[str] = []
    clean = str(text)

    for kind, pattern in (
        ("rate", RATE_CLAIM),
        ("amount", CURRENCY_CLAIM),
        ("score", SCORE_CLAIM),
        ("zone", ZONE_CLAIM),
    ):
        if pattern.search(clean):
            clean = pattern.sub(REPLACEMENTS[kind], clean)
            redactions.append(kind)

    return clean, redactions
