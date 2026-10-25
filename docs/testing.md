# Testing & Quality Assurance
> `pytest` • `Regression Suites` • `Topological Invariants` • `Puppeteer UI Audit` • `Oxlint`

Complete guide to testing, regression prevention, structural invariants validation, and UI audits across the BuildWise AI codebase.

---

## Table of Contents
- [Test Strategy Overview](#test-strategy-overview)
- [Backend Test Suites (`backend/tests/`)](#backend-test-suites-backendtests)
  - [Architectural Placement Regression Suite (`test_placement_rules.py`)](#architectural-placement-regression-suite-test_placement_rulespy)
  - [Generative Room Program Suite (`test_room_program_v10.py`)](#generative-room-program-suite-test_room_program_v10py)
  - [Formal PDF Report Suite (`test_pdf_report_v9.py`)](#formal-pdf-report-suite-test_pdf_report_v9py)
  - [API Contract & Rate Limit Suite (`test_api.py`)](#api-contract--rate-limit-suite-test_apipy)
  - [Geospatial & Hazard Suites](#geospatial--hazard-suites)
  - [Space-Engine, Gate & Economics Suites](#space-engine-gate--economics-suites)
    - [Per-module engine suites](#per-module-engine-suites)
- [Frontend Testing & Quality Gates](#frontend-testing--quality-gates)
  - [Linting with Oxlint](#linting-with-oxlint)
  - [TypeScript Compilation & Vite Build](#typescript-compilation--vite-build)
  - [Multi-Viewport Automated UI Audit (`audit.cjs`)](#multi-viewport-automated-ui-audit-auditcjs)
  - [Additional Quality Gates](#additional-quality-gates)
- [Running All Tests Locally](#running-all-tests-locally)
- [Navigation](#navigation)

---

## Test Strategy Overview

BuildWise AI employs a multi-tiered verification hierarchy ensuring that zero invalid architectural geometry or UI layout bugs reach production:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Continuous Quality Gates                        │
├──────────────────────────────────┬─────────────────────────────────────┤
│        Backend Verification      │        Frontend Verification        │
│  • 1,159 Automated Pytest Cases  │  • Oxlint Fast Static Analysis      │
│  • 145 Placement Regression Test │  • TypeScript Strict Typing (tsc)   │
│  • Vastu / Topological Invariant │  • Vite Production Bundling         │
│  • CPWD Mathematical Accuracy    │  • Puppeteer 9-Viewport Audit       │
└──────────────────────────────────┴─────────────────────────────────────┘
```

---

## Backend Test Suites (`backend/tests/`)

Backend test suites are run using `pytest` inside the Python virtual environment:
```bash
cd backend
python -m pytest tests/ -v
```

### Architectural Placement Regression Suite (`test_placement_rules.py`)
Encodes non-negotiable architectural invariants into 145 parameterized tests across 6 plot geometries and 3 typologies:

```python
TEST_PLOTS = [
    (10.9, 10.6),  # Square single-family plot
    (12.0, 10.0),  # Wide plot
    (10.0, 15.0),  # Deep plot
    (15.0, 12.0),  # Mid-size suburban
    (23.3, 14.0),  # Wide frontage plot
    (16.1, 19.3),  # Large residential estate
]

TEST_TYPOLOGIES = [
    ["living", "puja", "master_bed", "bath_1", "kitchen"],
    ["living", "puja", "master_bed", "bed_2", "bath_1", "kitchen"],
    ["living", "puja", "master_bed", "bed_2", "bath_1", "bath_2", "dining", "kitchen"],
]
```

#### Parameterized Test Matrix:
1. **`test_bath_never_adjacent_pooja`** (18 cases): Asserts that no bathroom/WC ever shares a vertical or horizontal wall segment ($> 0.15\text{m}$) with a Pooja room.
2. **`test_bath_never_at_entry_or_frontage`** (18 cases): Asserts that the main entry door never opens into a bathroom and no bathroom touches the front boundary wall.
3. **`test_bath_never_central`** (18 cases): Asserts that the centroid of every bathroom lies strictly outside the central 40% plot box.
4. **`test_bath_is_leaf`** (18 cases): Asserts that in the door connectivity graph, all bathroom nodes have degree exactly equal to 1 (zero through-traffic).
5. **`test_living_receives_entry`** (18 cases): Asserts that the main entry door opens directly into the Living Room.
6. **`test_pooja_ne_corner`** (18 cases): Asserts that the Pooja room sits in the North-East corner with width $\ge 2.4\text{m}$.
7. **`test_kitchen_se_corner`** (18 cases): Asserts that the Kitchen occupies the South-East corner and touches exterior envelope walls.
8. **`test_all_rooms_within_area_catalog_and_aspect`** (18 cases): Verifies that all room areas comply with the NBC 2016 room catalog bounds and aspect ratios $\le 1:2.2$.
9. **`test_validator_repairs_illegal_placement`**: Unit tests validating that `validate_and_repair_placement()` repairs faulty LLM placements before geometry solver execution.

---

### Generative Room Program Suite (`test_room_program_v10.py`)
- Verifies dynamic room program generation across diverse plinth areas (800 sqft to 5,000 sqft) and specification grades.
- Validates fallback program selection when LLM inference is disabled.
- Asserts that room programs respect client notes (e.g. requesting a home office, study, or additional ensuite).

---

### Formal PDF Report Suite (`test_pdf_report_v9.py`)
- Tests end-to-end vector PDF compilation in ReportLab.
- Verifies page layout constraints: A4 portrait, 18mm margins, Inter TTF font subsetting.
- Tests Section 10 dedicated full-page blueprint layout with the 4-tile solver metric strip and 174mm vector drawing.
- Ensures zero page-count overflow or orphaned heading elements.

---

### API Contract & Rate Limit Suite (`test_api.py`)
- Tests `POST /api/analyze` request validation and Pydantic response models.
- Tests sliding window in-memory rate limiting (asserts `HTTP 429` on the 31st request within 60s).
- **`test_external_provider_rate_limit.py`:** proves upstream 429s degrade honestly — Nominatim/Photon return no invented results, Overpass falls back to a named `ASSUMED` frontage, Groq drops to the deterministic mock with the `429` in `fallback_reason`.
- Tests CORS headers and preflight `OPTIONS` requests.
- Validates graceful degradation when external telemetry APIs simulate timeouts.

---

### Geospatial & Hazard Suites
- **`test_hazard.py`:** Tests USGS FDSN seismic parsing, 50-year filtering, and GloFAS river discharge ratio calculations.
- **`test_site_vision.py`:** Tests Copernicus Sentinel-2 multispectral vegetation index calculation (NDVI) and tree preservation clustering.
- **`test_cost.py`:** Tests CPWD Plinth Area Rate formulas and floor height adjustments.
- **`test_vastu.py`:** Tests 8-directional cardinal analysis and entrance scoring.

---

### Space-Engine, Gate & Economics Suites

The generative plan is verified by contract suites rather than a golden drawing, so a
solver change is judged by the same invariants the certificate and the report publish.
The architecture behind these suites is documented in [Space Engine](space-engine.md).

| Suite | What it pins |
|:---|:---|
| `test_validation_gate.py` | Every layer L1–L15 is evaluated, `N/A` never silently passes, the PDF sheet carries the same layer table as the UI |
| `test_gate_integrity.py` | Gate verdicts, refusal gates, and certificates are recomputed after mutation; a stale PASS cannot survive |
| `test_coverage_truth.py`, `test_plot_coverage_contract.py` | Captured boundary drives plate size; coverage is a hard cap, never an unwarned breach |
| `test_land_economics.py` | Land economics certificate: footprint source, residuals, dead corners, circulation band |
| `test_scheme_solver.py`, `test_scheme_selection.py`, `test_scheme_picker_wiring.py` | The three scheme profiles score deterministically, and choosing one **re-partitions** the plate (with the outcome recorded as applied / recorded only / refused) |
| `test_furniture_ventilation.py`, `test_living_quality_layers.py` | Furniture sets fit their rooms; ventilation and daylight layers are evaluated |
| `test_invariant_sweep_standing.py` | A standing multi-seed sweep keeps the hard invariants true across typologies |
| `test_sidebar_control_wiring.py` | Every sidebar control reaches a visible output — no dead control, no orphan payload field |
| `test_analyze_boundary.py` | Analysis plot area comes from the boundary, with the basis named |

---

#### The gate set — one command, one exit status

Every change that can move a drawn plan, a printed page or an invariant runs the
same commands. CI (`.github/workflows/ci.yml`) runs the backend gates and the
build/report-surface and selection-policy steps; the full browser set below is
run locally before delivery, and uses the same scripts CI runs.

| Gate | Command (from the stated directory) | Passes when |
|:---|:---|:---|
| Backend gates | `cd backend && python scripts/qa_gates.py` | the suite, the report/PDF/SVG parity contracts, rectangle equivalence, the cross-process matrix and the invariant sweep all pass |
| — of which matrix | `cd backend && python scripts/qa_circulation_determinism.py --matrix` | all 64 cases are generated in **two separate processes** (`PYTHONHASHSEED=0` and `=1`) and their warning lists, sponsor doors and door sets are byte-identical |
| — of which sweep | `cd backend && python scripts/qa_invariant_sweep.py` | its verdict names **0 TRUE FAILURES**; a DISCLOSED-only register is tolerated (the runner reads the verdict block, not just the exit code) |
| Build + report surface | `cd frontend && npm run gates` | `tsc -b && vite build`, then the L16 table / FAIL stamp / print-wiring pins pass |
| Browser gates | `cd frontend && npm run gates:browser` | the selection-policy pass, the full funnel pass and the UI-closure pass against live servers (`E2E_URL`, `CHROME_PATH`) |

`python scripts/qa_gates.py --list` prints the command set it runs, and
`--only sweep` runs one gate. The backend gates working directory is fixed to
`backend/` so node ids and sweep output paths resolve identically in CI.

---

#### Per-module engine suites
| Suite | What it locks down |
|:---|:---|
| `test_floorplan.py` | Grid discretisation, Vastu quadrant constraints, plumbing adjacency, disjointness/containment, dissection contiguity, SVG validity |
| `test_multi_floor_engine.py` | Vertical core stacking, cross-floor graph reachability, wet-stack alignment, graceful degradation (EC01–EC04), typology × storey × strictness matrix |
| `test_validation_gate.py` | The L1–L15 gate: severity typing, `pass/warn/na` tallies, a layer that did not run cannot pass, refusal honesty |
| `test_land_economics.py` | Programme-aware footprint, coverage ceiling, residual sliver absorption, explicit (never silent) programme deficit |
| `test_coverage_truth.py` | Captured-boundary coverage ceiling, plate fill, refusal on an unplaceable brief |
| `test_ontology_contracts.py` | Space semantics, symmetric relation matrix, vertical no-wet-over-habitable law, typology catalog completeness |
| `test_drawing_ir.py` / `test_drafting_hygiene.py` | Sheet parity with the model, bbox containment, `L0/L1` level ladders, `m²` typography, title-block fields |
| `test_living_quality_layers.py` | Layers 2–4: door swings, fixture clearances, furniture placement and kitchen working triangle |
| `test_pipeline_contracts.py` | API ↔ frontend response contract, wall-graph DTO, dimension-chain sum, sidebar single-source combinations |
| `test_proportions_and_wet_stack.py` | Frontage is capped at each space's catalogue proportion, bands are split so their rooms can fill them, every disproportionate room is named, and `VERT-01` is only claimed where the room measurably stacks |
| `test_compact_t2_unit_plan.py` | The 12 × 15 T2 plate holds both unit programmes: stair on the east flank, pocket bedroom + second bath, every room at its catalogue gross minimum, both living rooms opening off the lobby, no bath/kitchen shared wall (HYG-02), identical wet positions on every storey, and the row plan untouched on plates that already fit |
| `test_analyze_boundary.py` / `test_plot_coverage_contract.py` | Boundary echo, statutory-area rejection, area disagreement surfacing, traced boundaries never overhanging |
| `test_irregular_site_geometry.py` | Projection round-trip, self-intersection and narrow-wedge rejection, golden L-shape/courtyard cases, PDF parity |
| `test_report_honesty_parity.py` / `test_pdf_hygiene_parity.py` | Warnings verbatim in UI and PDF, null seismic zone never rendered as a letter, no mid-word PDF truncation |

#### Engine scripts (`backend/scripts/`)
```bash
cd backend

# Cross-typology invariant sweep -> docs_ignore/space-engine/qa-sweep.{json,md}
python scripts/qa_invariant_sweep.py --quick

# Re-freeze the landing hero geometry the 3D massing extrudes from
python scripts/capture_landing_generation.py
```
`qa_invariant_sweep.py` runs every typology × plot × storey × strictness combination through the real solver and writes a violation register; `--only`, `--typology`, `--suffix` narrow or label a run. `capture_landing_generation.py` calls the same function as `POST /api/generate-floorplan` with `ai_provider="mock"` and a fixed seed, so re-running reproduces the landing asset byte-for-byte (timestamps excluded from the provenance hash).

---

## Frontend Testing & Quality Gates

The frontend employs static analysis, type checking, and automated browser audits:

### Linting with Oxlint
Fast static code analysis powered by [Oxlint](https://oxc.rs/):
```bash
npm run lint
```

### TypeScript Compilation & Vite Build
Validates that all React components, hooks, and types compile with zero type errors:
```bash
npm run build
```
Executes `tsc -b && vite build`.

### Multi-Viewport Automated UI Audit (`audit.cjs`)
Located in `frontend/scripts/audit.cjs`. Uses headless Chrome via Puppeteer to evaluate 9 responsive screen resolutions:

| Viewport | Dimensions (WxH) | Target Device Class |
|:---|:---|:---|
| **2560x1440** | 2560 × 1440 | 2K / 4K Desktop Monitors |
| **1920x1080** | 1920 × 1080 | Standard Full HD Desktop |
| **1536x900** | 1536 × 900 | Common High-DPI Laptops |
| **1535x900** | 1535 × 900 | High-DPI Breakpoint Boundary |
| **1366x768** | 1366 × 768 | Legacy Desktop / Budget Laptops |
| **1024x768** | 1024 × 768 | iPad / Small Tablets (Landscape) |
| **900x1000** | 900 × 1000 | Tiled Window / Foldable Screen |
| **768x1024** | 768 × 1024 | Tablet Portrait |
| **390x844** | 390 × 844 | Modern Mobile Smartphone |

#### Automated Audit Checks:
- [x] **Zero Page Overflow:** Asserts `document.documentElement.scrollWidth <= window.innerWidth`.
- [x] **No Clipped Text:** Identifies truncated labels or overflow issues.
- [x] **Drawer Collisions:** Confirms that floating glass cards and the sliding ReportSheet do not overlap the top navigation or map tools.
- [x] **Accessible Tap Targets:** Verifies buttons and inputs meet the 44×44px minimum target standard.

To execute the audit:
```bash
npm run audit:ui
```

### Additional Quality Gates

Beyond the viewport audit, these commands prove specific contracts. They run against the
built tree (`vite preview` on port 4173 for `audit:landing`) or the dev servers on
`localhost:5173` + `localhost:8000` where noted.

| Command | Contract it proves |
|:---|:---|
| `node scripts/test_boundary_pipeline.cjs` | Projection parity, boundary canonicalisation, gate layer ids (L1–L15), sheet-truth chips, frontage callouts |
| `node scripts/test_unified_source.cjs` | One source of truth for the capture → analysis → report payload |
| `npm run test:design` | Design-token grammar and interaction primitives |
| `npm run test:interaction` | Focus, keyboard and pressed-state behaviour |
| `npm run test:map-controls` | Map control offsets against the HUD |
| `npm run test:trace-ui` | Capture wizard tracing flow |
| `npm run lint:tokens` · `lint:emoji` · `lint:css` | No ad-hoc colour literals, no banned glyphs, no orphan CSS |
| `npm run lint:material` | Every blur/translucency surface is classified chrome (pinned ledger; regenerate with `--update`) |
| `npm run check:contrast` | Text contrast against the design tokens |
| `npm run assert:bundle` | Route-level bundle split is intact |
| `npm run test:e2e` *(dev servers required)* | Full funnel in Chromium: capture → analysis → blueprint, including land economics, the scheme picker re-solving the plate, the 390 px report section-nav fade, the frontage vertex pair and float-free numeric inputs |
| `node scripts/audit_sidebar_wiring.cjs` *(dev servers required)* | Every sidebar control moves a visible output, light + dark proofs, dropdown/menu keyboard behaviour |
| `npm run audit:landing` *(preview build on 4173)* | Landing console, axe, overflow, CLS and LCP across viewports, 44 px tap targets and the fixed porcelain palette under an OS `prefers-color-scheme: dark` preference. The landing is intentionally light-only (see `index.css`); the dark pass asserts it stays porcelain rather than inverting. Exits non-zero on console/page errors, axe violations, undersized targets, document overflow or an inverted palette |

---

## Running All Tests Locally

Run the complete test cycle before submitting pull requests:

```bash
# 1. Run backend unit & regression suites
cd backend
python -m pytest tests/

# 2. Run frontend type check, lint, and production bundle
cd ../frontend
npm run lint
npm run build
```

---

## Navigation
- **Previous:** [← Map & Data Providers](map-and-data.md)
- **Next:** [Production Deployment →](deployment.md)

---
*BuildWise AI • [MIT License](../LICENSE) • Copyright (c) 2026 Rolan Lobo*
