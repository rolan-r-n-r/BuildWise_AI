"""The floorplan advisor words facts; it never supplies one.

Pins:
  * an invented number (``3 storeys``, ``99``, ``Rs 1/sqft``, ``Zone V``) is
    removed from the narrative and the removal is disclosed;
  * the response is labelled advisory_non_certified;
  * a plan hash is explained once (cache hit is disclosed);
  * a provider failure returns narrative=None with a disclosed reason, leaving
    the deterministic summary as the only truth on screen.
"""
import asyncio

import pytest

from app.ai import floorplan_advisor as advisor
from app.schemas.remediation import AdvisoryIn, AdvisoryOption


def _payload():
    return AdvisoryIn(
        plan_hash="plan-abc-123",
        plan_verdict="NOT-CERTIFIED-FAIL-STAMP",
        summary_line=(
            "55 engine messages · 27 certificate failures · 7 advisories · "
            "21 engine operations excluded from warnings"
        ),
        blocking_reasons=[
            "PROP-HARD: living_F0 3.00 m clear < 3.60 m minimum",
            "ROOM-MIN: core_staircase_primary_F0 is 7.2 m², below 8.0 m²",
            "GATE-FAIL L16 Proportion & Surplus",
        ],
        warning_counts={"total": 55, "failures": 27, "advisories": 7, "operations": 21},
        options=[
            AdvisoryOption(
                id="add_storey",
                title="Add a storey (G+2 → G+3)",
                effect_line="3 certificate failures · 73 messages · plate 82.8 m²",
            ),
            AdvisoryOption(
                id="reduce_programme",
                title="Reduce programme",
                effect_line="3 certificate failures · 52 messages · plate 82.8 m²",
            ),
        ],
        allowed_numbers=["55", "27", "7", "21", "3", "73", "52", "82.8", "2", "8.0"],
    )


@pytest.fixture(autouse=True)
def clear_cache():
    advisor.clear_cache()
    yield
    advisor.clear_cache()


def test_invented_numbers_are_redacted_and_disclosed(monkeypatch):
    async def hostile(_payload, _key):
        return (
            "The plan fails because the living room is short. Add 3 storeys and "
            "41 rooms; you will reach a score of 99 at Rs 1/sqft in Zone V.",
            "groq (hostile-test)",
            None,
        )

    monkeypatch.setattr(advisor, "_ask_groq", hostile)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    out = asyncio.run(advisor.advise(_payload()))

    assert out.narrative is not None
    assert "3 storeys" not in out.narrative
    assert "41 rooms" not in out.narrative
    assert "99" not in out.narrative
    assert "Zone V" not in out.narrative
    assert "Rs 1" not in out.narrative
    assert not any("0" <= ch <= "9" for ch in out.narrative)
    assert {"rate", "score", "zone"} & set(out.meta.redactions)
    assert "outcome_claim" in out.meta.redactions
    assert {"zone", "rate", "amount"} & set(out.meta.redactions)
    assert out.meta.narrative_class == "advisory_non_certified"
    assert out.meta.provider_used == "groq (hostile-test)"


def test_advisor_writes_no_numbers_at_all(monkeypatch):
    """Numbers live on the cards; the narrative may not restate even a true one."""

    async def verbose(_payload, _key):
        return (
            "The plate carries 27 certificate failures out of 55 engine messages. "
            "Adding a storey measures 73 messages for the same programme. "
            "The plan is fully certified.",
            "groq (verbose-test)",
            None,
        )

    monkeypatch.setattr(advisor, "_ask_groq", verbose)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    out = asyncio.run(advisor.advise(_payload()))
    assert not any("0" <= ch <= "9" for ch in out.narrative), out.narrative
    assert out.narrative.count("[number removed]") == 3
    assert "number_written" in out.meta.redactions
    assert "fully certified" not in out.narrative
    assert "verdict_claim" in out.meta.redactions


def test_negated_status_keeps_the_reason(monkeypatch):
    """The plan's own NOT-CERTIFIED state is the server's verdict, not a claim.

    Stripping every 'certificat*' clause used to delete the WHY itself: the model
    writes "not certified because ...", and the reason went with the negation.
    Only affirmative claims may go; the causal reason must survive.
    """

    async def honest(_payload, _key):
        return (
            "The plan is not certified because the living spaces cannot meet "
            "their required proportion on the current plate. "
            "This layout is fully compliant.",
            "groq (negation-test)",
            None,
        )

    monkeypatch.setattr(advisor, "_ask_groq", honest)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    out = asyncio.run(advisor.advise(_payload()))
    assert out.narrative and "cannot meet their required proportion" in out.narrative
    assert "fully compliant" not in out.narrative
    assert "verdict_claim" in out.meta.redactions


def test_outcome_promises_are_dropped_and_disclosed(monkeypatch):
    async def promising(_payload, _key):
        return (
            "The living room cannot meet its proportion on this plate. "
            "Adding a storey would remove a few certificate failures and lower "
            "the engine messages. Reducing the programme would cut the failures.",
            "groq (promise-test)",
            None,
        )

    monkeypatch.setattr(advisor, "_ask_groq", promising)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    out = asyncio.run(advisor.advise(_payload()))
    assert "living room cannot meet its proportion" in out.narrative
    assert "certificate failures" not in out.narrative
    assert "cut the failures" not in out.narrative
    assert "outcome_claim" in out.meta.redactions


def test_option_notes_are_parsed_and_sanitized(monkeypatch):
    async def structured(_payload, _key):
        return (
            "WHY: The living room cannot meet its proportion on this plate.\n"
            "OPTION add_storey: Adding a level gives the squeezed programme more room to spread out.\n"
            "OPTION reduce_programme: Removing the named rooms leaves a smaller programme on the same plate.\n"
            "OPTION invented_option: This option does not exist and must be dropped.",
            "groq (structured-test)",
            None,
        )

    monkeypatch.setattr(advisor, "_ask_groq", structured)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    out = asyncio.run(advisor.advise(_payload()))
    assert out.narrative and "living room" in out.narrative
    assert set(out.option_notes) == {"add_storey", "reduce_programme"}
    assert "invented_option" not in out.option_notes
    assert "level" in out.option_notes["add_storey"]
    assert "Removing" in out.option_notes["reduce_programme"]


def test_single_line_option_wording_still_reaches_the_cards(monkeypatch):
    """A one-line answer must not swallow the per-option wording.

    Observed live: the model answered in ONE line - "... prevents certification.
    OPTION add_storey: ... OPTION reduce_programme: ..." - and the
    newline-only splitter treated the whole answer as WHY, so the narrative
    contained the option sentences and the cards rendered no wording at all.
    """

    async def one_line(_payload, _key):
        return (
            "The living room cannot achieve its required minimum proportion on "
            "the current plate, and the validation gate for that layer fails. "
            "OPTION add_storey: adds an additional level to the building. "
            "OPTION reduce_programme: lowers the overall programme requirements.",
            "groq (one-line-test)",
            None,
        )

    monkeypatch.setattr(advisor, "_ask_groq", one_line)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    out = asyncio.run(advisor.advise(_payload()))
    assert set(out.option_notes) == {"add_storey", "reduce_programme"}
    assert "additional level" in out.option_notes["add_storey"]
    assert "programme requirements" in out.option_notes["reduce_programme"]
    # The option sentences are wording for their cards, not part of the WHY.
    assert out.narrative and "OPTION" not in out.narrative
    assert "living room" in out.narrative


def test_cached_per_plan_hash(monkeypatch):
    calls = {"n": 0}

    async def honest(_payload, _key):
        calls["n"] += 1
        return ("The plan fails on the living-room proportions.", "groq (cache-test)", None)

    monkeypatch.setattr(advisor, "_ask_groq", honest)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    first = asyncio.run(advisor.advise(_payload()))
    second = asyncio.run(advisor.advise(_payload()))
    assert calls["n"] == 1
    assert first.meta.cached is False
    assert second.meta.cached is True
    assert second.narrative == first.narrative


def test_provider_failure_returns_deterministic_fallback(monkeypatch):
    async def broken(_payload, _key):
        return (None, "unavailable", "ReadTimeout: advisor timed out")

    monkeypatch.setattr(advisor, "_ask_groq", broken)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    out = asyncio.run(advisor.advise(_payload()))
    assert out.narrative is None
    assert out.meta.provider_used == "deterministic_only"
    assert "timed out" in (out.meta.fallback_reason or "")
    assert out.meta.narrative_class == "advisory_non_certified"


def test_missing_key_is_disclosed(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(advisor.settings, "GROQ_API_KEY", "")
    out = asyncio.run(advisor.advise(_payload()))
    assert out.narrative is None
    assert "GROQ_API_KEY" in (out.meta.fallback_reason or "")


def test_affirmative_only_filter_keeps_a_plain_status_word():
    text, removed = advisor.strip_verdict_clauses(
        "The plan is not certified because the stair is below its width. "
        "The certificate is withheld. The design is now certified."
    )
    assert "stair is below its width" in text
    assert "certificate is withheld" in text.lower()
    assert "design is now certified" not in text.lower()
    assert removed == ["The design is now certified."]


def test_number_guard_removes_every_digit():
    text, removed = advisor.strip_all_numbers(
        "The plate is 82.8 m² and the certificate lists 27 failures; G+3 adds 41 rooms."
    )
    assert removed == ["82.8", "27", "3", "41"]
    assert not any("0" <= ch <= "9" for ch in text)
    assert text.count("[number removed]") == 4
