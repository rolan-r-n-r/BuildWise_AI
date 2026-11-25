"""Scheme picker wiring gate: the picker must re-solve, the panel must print the certificate.

Static source assertions for the picker and panel surfaces. They exist because both
failures are invisible at runtime: a picker that only sets a label still renders,
and a land-economics panel that recomputes its own KPIs still looks right.
"""
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "src"

CARD = FRONTEND / "components" / "FloorPlanGeneratorCard.tsx"
PICKER = FRONTEND / "components" / "SchemePicker.tsx"
PANEL = FRONTEND / "components" / "report" / "LandEconomicsPanel.tsx"
SHEET = FRONTEND / "components" / "ReportSheet.tsx"


def _read(path: Path) -> str:
    assert path.exists(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def test_card_requests_the_portfolio_and_sends_the_selection():
    src = _read(CARD)
    assert "include_scheme_alternatives: true" in src
    assert re.search(r"selected_scheme_id:\s*activeSchemeProfile", src), (
        "the selected profile must travel with the request"
    )


def test_selecting_a_profile_re_solves_through_the_same_funnel():
    src = _read(CARD)
    handler = re.search(
        r"const handleSelectScheme = \(schemeId: string\) => \{(?P<body>.*?)\n  \};",
        src,
        re.S,
    )
    assert handler, "handleSelectScheme is missing"
    body = handler.group("body")
    assert "handleGenerate(schemeId)" in body, (
        "picking a profile must re-solve, not just store an id"
    )
    assert re.search(r"<SchemePicker[^>]*onSelect=\{handleSelectScheme\}", src, re.S)


def test_picker_states_what_the_backend_did():
    src = _read(PICKER)
    for status in ("applied", "rejected_non_compliant", "recorded_only"):
        assert status in src
    # The badge is driven by the recorded status, never by "a profile is set".
    assert "selectionStatus" in src
    assert "data-testid=\"scheme-selection-status\"" in src


def test_land_economics_panel_prints_the_certificate_it_was_given():
    panel = _read(PANEL)
    assert "LandEconomicsReport" in panel
    assert "certificate" in panel
    assert "cert?.checks" in panel or "cert.checks" in panel or "checks" in panel
    assert "data-testid=\"land-economics-checks\"" in panel
    # No browser-side arithmetic on the certified KPIs: values are formatted from
    # the response, so the panel can never disagree with the gate.
    assert "land_use_efficiency_pct *" not in panel
    assert "/ report.program_needed_area_m2" not in panel

    sheet = _read(SHEET)
    assert "LandEconomicsPanel" in sheet
    assert "data-report-section=\"land\"" in sheet
    assert "{ id: 'land', label: 'Land & Space' }" in sheet
