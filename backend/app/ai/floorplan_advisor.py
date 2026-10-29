"""floorplan_advisor.py - the advisor words the engine's facts, nothing else.

The remediation contract is strict: the engine decides which options exist and
what each one measures; the browser renders those options verbatim. This module
adds an advisory paragraph - why the plan failed, in plain language, and what
each listed option changes - and enforces the boundary:

  * no number the engine did not provide survives in the narrative;
  * no currency / score / seismic-zone claim survives (QA-03 sanitizer);
  * the response is labelled ``advisory_non_certified``;
  * a timeout or missing key falls back to ``narrative=None`` with a disclosed
    reason, and the deterministic summary already on screen stays authoritative.

Cached per plan hash: the same plan is explained once.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

import httpx

from app.config import settings
from app.schemas.remediation import AdvisoryIn, AdvisoryMeta, AdvisoryOut
from app.services.ai_narrative import sanitize_narrative

CACHE: "OrderedDict[str, Tuple[Optional[str], Dict[str, str], AdvisoryMeta]]" = OrderedDict()
CACHE_MAX = 64
ADVISOR_TIMEOUT_S = 7.0

SYSTEM_PROMPT = (
    "You are a building-design advisor. The deterministic geometry engine has "
    "already decided the plan, its verdict, which remediation options exist, "
    "and what each option measured when re-solved. Explain to the architect, in "
    "plain language, why the plan failed and what each listed option "
    "changes. Rules: use ONLY the listed options; never invent an option, room, "
    "dimension, cost or score; do not claim the plan is compliant; do not promise "
    "an outcome beyond the measured effect. Describe what each option changes "
    "physically (a level, the programme, the plot axis, the coverage, the scheme "
    "profile), never what it will achieve. Use ONLY the supplied blocking "
    "reasons; do not infer additional causes and do not mention certification, "
    "compliance or achievement. The measured numbers are already "
    "printed beside each option, so write NO digits, counts, areas, dimensions, "
    "percentages, storey labels or verdict strings - refer to the measured effect "
    "instead. Two short paragraphs, 90 words maximum, no headings, no bullets, no "
    "markdown, no JSON. Reply EXACTLY in this plain-text format and nothing "
    "else:\nWHY: <two sentences on why the plan failed>\n"
    "OPTION <option id>: <one sentence on the physical design change that "
    "option makes>\n(repeat one OPTION line for each supplied option id)."
)

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
STOREY_CLAIM = re.compile(r"\b(?:G\s*\+\s*)?(\d+)\s*storeys?\b", re.IGNORECASE)
# Outcome promises are the one thing a qualitative explanation cannot make: the
# engine measured the effect, the advisor may not predict a different one.
OUTCOME_CLAIM = re.compile(
    r"\b(?:would|will|should)\b[^.]{0,120}?\b(?:fewer|lower|reduce\w*|cuts?|cut\w*|"
    r"eliminat\w*|improv\w*|pass\w*|reach\w*|meet\w*|satisf\w*|score\w*|"
    r"compliant|certif\w*|resolv\w*)\b",
    re.IGNORECASE,
)
COUNTER_CLAIM = re.compile(
    r"\b(?:reduc\w*|lower\w*|cut\w*|eliminat\w*|remov\w*|clear\w*|trims?|shrinks?|"
    r"drops?|eases?)\b[^.]{0,60}\b"
    r"(?:failures?|warnings?|messages?|relaxations?|deficits?)\b",
    re.IGNORECASE,
)


def _facts(payload: AdvisoryIn) -> Dict[str, object]:
    return {
        "verdict": payload.plan_verdict,
        "summary": payload.summary_line,
        "counts": payload.warning_counts,
        "blocking_reasons": payload.blocking_reasons[:3],
        "options": [o.model_dump() for o in payload.options],
    }


def strip_storey_claims(text: str, payload: AdvisoryIn) -> Tuple[str, List[str]]:
    """A storey claim survives only if the option titles state that exact phrase."""
    allowed_text = " ".join(
        [payload.summary_line, *[f"{o.title} {o.effect_line}" for o in payload.options]]
    ).lower()
    removed: List[str] = []

    def _swap(match: re.Match[str]) -> str:
        if match.group(0).lower() in allowed_text:
            return match.group(0)
        removed.append(match.group(0))
        return "[storey count removed]"

    return STOREY_CLAIM.sub(_swap, text), removed


STATUS_WORD = re.compile(r"\b(?:certified|compliant|compliance|certification)\b", re.IGNORECASE)
STATUS_VERB = re.compile(
    r"\b(?:achiev\w*|ensur\w*|secur\w*|makes?|renders?|pass(?:es|ed)?|meets?|satisf\w*)\b",
    re.IGNORECASE,
)
NEGATIONS = ("not ", "never ", "cannot ", "can't ", "isn't ", "wasn't ", "fails to ", "fail to ", "unable to ")


def _asserts_positive_status(clause: str) -> bool:
    """True only for an affirmative status claim, never for its negation.

    "The plan is not certified because the living room is narrow" keeps its
    reason; "this layout is fully compliant" goes. A bare noun such as
    "certification failures" is not a claim on its own.
    """
    low = clause.lower()
    for match in STATUS_WORD.finditer(low):
        prefix = low[max(0, match.start() - 28) : match.start()]
        if any(neg in prefix for neg in NEGATIONS):
            continue
        if match.group(0) in {"compliance", "certification"} and not STATUS_VERB.search(low):
            continue
        return True
    return False


def strip_verdict_clauses(text: str) -> Tuple[str, List[str]]:
    """Remove clauses that assert compliance or certification.

    Clause-level rather than sentence-level: a note may legitimately describe the
    physical change and then append a verdict remark; only the remark goes. The
    plan's actual NOT-CERTIFIED state may be restated - that is the server's
    verdict, not a new one.
    """
    kept_sentences: List[str] = []
    removed: List[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        clauses = [c.strip() for c in sentence.split(",") if c.strip()]
        good: List[str] = []
        for clause in clauses:
            if _asserts_positive_status(clause):
                removed.append(clause)
            else:
                good.append(clause)
        if good:
            joined = ", ".join(good)
            joined = re.sub(r"^(?:and|but|so|while|yet)\s+", "", joined, flags=re.IGNORECASE)
            if joined:
                kept_sentences.append(joined)
    out = " ".join(kept_sentences).strip()
    if out:
        out = out[:1].upper() + out[1:]
    return out, removed


def strip_outcome_claims(text: str) -> Tuple[str, List[str]]:
    """Drop any sentence that predicts an outcome the engine did not state."""
    kept: List[str] = []
    removed: List[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if not sentence.strip():
            continue
        if OUTCOME_CLAIM.search(sentence) or COUNTER_CLAIM.search(sentence):
            removed.append(sentence.strip()[:120])
            continue
        kept.append(sentence.strip())
    return " ".join(kept), removed


def strip_all_numbers(text: str) -> Tuple[str, List[str]]:
    """The advisor may not write a number at all - the cards carry them."""
    removed: List[str] = []

    def _swap(match: re.Match[str]) -> str:
        removed.append(match.group(0))
        return "[number removed]"

    return NUMBER_RE.sub(_swap, text), removed


def _cache_get(key: str) -> Optional[Tuple[Optional[str], Dict[str, str], AdvisoryMeta]]:
    hit = CACHE.get(key)
    if hit is None:
        return None
    CACHE.move_to_end(key)
    narrative, notes, meta = hit
    return narrative, notes, meta.model_copy(update={"cached": True})


def _cache_put(
    key: str,
    narrative: Optional[str],
    notes: Dict[str, str],
    meta: AdvisoryMeta,
) -> None:
    CACHE[key] = (narrative, notes, meta)
    CACHE.move_to_end(key)
    while len(CACHE) > CACHE_MAX:
        CACHE.popitem(last=False)


def clear_cache() -> None:
    CACHE.clear()


async def _ask_groq(payload: AdvisoryIn, api_key: str) -> Tuple[Optional[str], str, Optional[str]]:
    models = [
        os.getenv("GROQ_ADVISOR_MODEL"),
        getattr(settings, "GROQ_MODEL", None),
        "openai/gpt-oss-120b",
        "llama-3.3-70b-versatile",
    ]
    seen: set[str] = set()
    candidates = [m for m in models if m and not (m in seen or seen.add(m))]
    errors: List[str] = []
    for model in candidates:
        try:
            async with httpx.AsyncClient(timeout=ADVISOR_TIMEOUT_S) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": "FACTS:\n"
                                + json.dumps(_facts(payload), ensure_ascii=False),
                            },
                        ],
                        "temperature": 0.2,
                        "max_tokens": 800,
                        "reasoning_effort": "low",
                    },
                )
            if resp.status_code != 200:
                detail = ""
                try:
                    detail = str((resp.json().get("error") or {}).get("message") or "")[:80]
                except Exception:  # noqa: BLE001
                    detail = resp.text[:80]
                errors.append(f"{model}: HTTP {resp.status_code}{(' — ' + detail) if detail else ''}")
                continue
            content = resp.json()["choices"][0]["message"]["content"]
            text = str(content or "").strip()
            # Some models still wrap the answer in JSON; accept both shapes.
            if text.startswith("{"):
                try:
                    text = str(json.loads(text).get("explanation") or text).strip()
                except json.JSONDecodeError:
                    pass
            text = text.strip('"').replace("\\n", " ").strip()
            if not text:
                errors.append(f"{model}: empty explanation")
                continue
            return text, f"groq ({model})", None
        except Exception as exc:  # noqa: BLE001 - fall back, disclose the reason
            errors.append(f"{model}: {type(exc).__name__}: {str(exc)[:100]}")
    reason = errors[0] if errors else "Groq advisor unavailable"
    if len(errors) > 1:
        reason += f" (+{len(errors) - 1} more model attempts)"
    return None, "unavailable", reason


# A section starts at a newline OR at a sentence boundary immediately before
# an ``OPTION <id>:`` / ``WHY:`` marker.  Models frequently answer on one line
# ("... prevents certification. OPTION add_storey: ... OPTION reduce_programme:
# ..."), and splitting on newlines alone left the whole answer as WHY - every
# per-option wording was swallowed into the narrative and no note reached the
# cards.
_SECTION_SPLIT = re.compile(
    r"(?:\n+|(?<=[.!?])\s+)(?=(?:OPTION\s+[A-Za-z_]+\s*:)|(?:WHY\s*:))",
    re.IGNORECASE,
)
_OPTION_HEAD = re.compile(r"OPTION\s+([A-Za-z_]+)\s*:\s*(.*)", re.IGNORECASE | re.DOTALL)


def split_sections(raw: str, option_ids: List[str]) -> Tuple[str, Dict[str, str]]:
    """Parse the WHY block and per-option notes; unknown ids are ignored."""
    why_parts: List[str] = []
    notes: Dict[str, str] = {}
    allowed = {str(i) for i in option_ids}
    for block in _SECTION_SPLIT.split(raw):
        block = block.strip()
        if not block:
            continue
        if re.match(r"WHY\s*:", block, re.IGNORECASE):
            why_parts.append(re.sub(r"^WHY\s*:\s*", "", block, flags=re.IGNORECASE))
            continue
        match = _OPTION_HEAD.match(block)
        if match:
            option_id = match.group(1).strip().lower()
            note = " ".join(match.group(2).split())
            if option_id in allowed and note:
                notes[option_id] = note
            continue
        # Prose before the first marker is still WHY: dropping it would hide
        # the model's own explanation of the failure.
        why_parts.append(block)
    return " ".join(part.strip() for part in why_parts if part.strip()), notes


def _fallback_meta(reason: str, cached: bool = False) -> AdvisoryMeta:
    return AdvisoryMeta(
        provider_requested="groq",
        provider_used="deterministic_only",
        fallback_reason=reason,
        cached=cached,
    )


async def advise(payload: AdvisoryIn) -> AdvisoryOut:
    started = time.perf_counter()
    key = payload.plan_hash.strip()
    cached = _cache_get(key)
    if cached is not None:
        narrative, notes, meta = cached
        return AdvisoryOut(narrative=narrative, option_notes=notes, meta=meta)

    provider = (payload.provider or "groq").lower()
    if provider == "mock":
        meta = _fallback_meta("Advisor disabled (deterministic summary only)")
        _cache_put(key, None, {}, meta)
        return AdvisoryOut(narrative=None, meta=meta)

    api_key = os.getenv("GROQ_API_KEY") or getattr(settings, "GROQ_API_KEY", "")
    if not api_key:
        meta = _fallback_meta("GROQ_API_KEY is not configured")
        _cache_put(key, None, {}, meta)
        return AdvisoryOut(narrative=None, meta=meta)

    raw, used, error = await _ask_groq(payload, api_key)
    if raw is None:
        meta = _fallback_meta(error or "Groq advisor unavailable")
        _cache_put(key, None, {}, meta)
        return AdvisoryOut(narrative=None, meta=meta)

    why_raw, notes_raw = split_sections(raw, [o.id for o in payload.options])
    if not why_raw and not notes_raw:
        # A model that ignored the format still gets its prose treated as WHY;
        # every guard below applies unchanged.
        why_raw = raw
    redactions: List[str] = []

    def _clean(text: str) -> str:
        # Verdict stripping FIRST: the sanitizer's own placeholders speak of
        # "the certified cost table", and running the status filter afterwards
        # deleted the very sentence whose numbers had just been removed.
        clean, verdicts = strip_verdict_clauses(text)
        clean, reds = sanitize_narrative(clean)
        redactions.extend(reds)
        clean, outcomes = strip_outcome_claims(clean)
        clean, storeys = strip_storey_claims(clean, payload)
        clean, digits = strip_all_numbers(clean)
        if verdicts:
            redactions.append("verdict_claim")
        if outcomes:
            redactions.append("outcome_claim")
        if storeys:
            redactions.append("storey_count")
        if digits:
            redactions.append("number_written")
        return " ".join(clean.split()).strip()

    why = _clean(why_raw)
    notes = {oid: _clean(note) for oid, note in notes_raw.items()}
    notes = {oid: note for oid, note in notes.items() if note}
    if not why and not notes:
        meta = _fallback_meta("Groq returned no usable explanation")
        _cache_put(key, None, {}, meta)
        return AdvisoryOut(narrative=None, meta=meta)

    meta = AdvisoryMeta(
        provider_requested="groq",
        provider_used=used,
        redactions=list(dict.fromkeys(redactions)),
        generation_time_ms=round((time.perf_counter() - started) * 1000.0, 1),
    )
    _cache_put(key, why or None, notes, meta)
    return AdvisoryOut(narrative=why or None, option_notes=notes, meta=meta)
