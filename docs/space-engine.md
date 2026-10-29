# Space Engine
> `Deterministic Solver` • `Ontology as Data` • `L1–L15 Gate` • `Invariant Sweep` • `Certificates`

How BuildWise turns a plot, a typology and a programme into a certified floor plan —
and how you can verify the claim yourself instead of trusting the sheet.

The engine contains no LLM. Every room rectangle, corridor, core and wet stack is
produced by deterministic geometry code from the request; language models are used
upstream (planning the brief, critiquing a drawing), never inside the solve.

On compact dual-unit plates the plan is a **pocket plan**, not a wider row: the
stair moves to the east flank, one unit's bedroom and the other unit's bathroom
occupy the freed pocket beside the stair band, and both living rooms keep the
frontage they need. Stacking the bath over the kitchen — the obvious way to free
frontage — is rejected by the ontology's own HYG-02 law and never emitted.

---

## Table of Contents
- [Pipeline](#pipeline)
- [Engine subsystems and contracts](#engine-subsystems-and-contracts)
- [Two independent judges: gate layers and sweep invariants](#two-independent-judges-gate-layers-and-sweep-invariants)
- [Certification, declines and remediation](#certification-declines-and-remediation)
- [Verifying it yourself](#verifying-it-yourself)
- [Current status](#current-status)
- [Navigation](#navigation)

---

## Pipeline

One entry point, dispatched by typology, with single-sourced statics:

```text
FloorPlanRequest
  └─ generate_floor_plan()               floorplan/floorplan_service.py
      └─ SoleGeometryEngine(req)         floorplan/engine.py
          ├─ _compute_envelope()         NBC setbacks, coverage cap; irregular sites
          │                              via compute_canonical_site_plan() (site_geometry.py)
          ├─ _lock_vertical_anchors()    stair/duct cores, identical on every storey
          ├─ _resolve_floor_plate_masks() wing bands as present / terrace / void
          ├─ _partition_floor_plate()    per-typology partitioners (T1–T4)
          └─ evaluate_validation_gate() L1–L15 stack + certificate
              └─ drawing_ir.py           SVG / ReportLab PDF sheets from the same model
```

| Layer | Module | Responsibility |
|:--|:--|:--|
| Service | `floorplan/floorplan_service.py` | public entry point, cache bypass, response assembly |
| Engine | `floorplan/engine.py` | envelope, cores, bands, partitioners, warnings |
| Ontology | `floorplan/ontology.py` | 57 space types: zone, hygiene class, minima, relations, furniture sets |
| Solver | `floorplan/constrained_solver.py` | constrained rectangular-plate placement for the scheme portfolio |
| Schemes | `floorplan/scheme_solver.py` | ranked alternatives behind `include_scheme_alternatives` |
| Land economics | `floorplan/land_economics.py` | programme demand vs buildable, residual absorption |
| Identity | `floorplan/identity.py` | one resolved name per space, shared by model, schedule, SVG, PDF |
| Gate | `floorplan/validation_gate.py` | L1–L15 evaluation and the certificate |
| Drawing | `floorplan/drawing_ir.py` | vector sheets that read only the model |

## Engine subsystems and contracts

Each subsystem is verified by its own regression suite:

| Subsystem | What it makes true | Where |
|:--|:--|:--|
| Ontology as data | Every space carries a zone, hygiene class, furniture set, clear-area basis and orientation preferences; 57 catalogue entries; relations algebra for forbidden / facing / above pairs | `ontology.py`, `tests/test_coverage_truth.py`, `tests/test_ontology_contracts.py` |
| Constrained solver & schemes | Deterministic plate solver plus three ranked profiles (`max_area`, `max_light_vent`, `max_vastu`) that can actually be selected and re-solved | `constrained_solver.py`, `scheme_solver.py`, `tests/test_scheme_selection.py`, `tests/test_scheme_solver.py` |
| Land economics | Programme area demanded from the ontology, programme-aware footprint (opt-in), residual absorption, and a land report on every response | `land_economics.py`, `tests/test_land_economics.py` |
| Identity as naming source | Model label, wall-graph schedule, SVG text, PDF legend and service classification all read one `SpaceIdentity` | `identity.py`, `tests/test_scheme_picker_wiring.py`, `tests/test_space_identity.py` |
| Furniture & fresh air | The plate is divided against the real furniture catalogue, not audited afterwards; every wet room leaves the solver with a ventilation path, so L4 and L9 stop discovering failures the dimensions made inevitable | `furniture.py`, `tests/test_furniture_ventilation.py`, `tests/test_proportions_and_wet_stack.py` |
| Typology programme | The generation records the typology it actually built, emits that typology's programme (kitchen / utility / balcony included for T2) and names the same rooms on every surface | `typologies/`, `room_aliases.py`, `tests/test_room_program_v10.py` |
| Compact apartment unit plan | The canonical 12 × 15 T2 plate stops publishing 11.7 m² living rooms: the stair moves to the east flank and the freed pocket carries Unit A's bedroom plus Unit B's bathroom, so both units meet every catalogue gross minimum without stacking a bath against a kitchen (HYG-02) | `engine.py` (`_t2_pocket_plan`), `tests/test_compact_t2_unit_plan.py` |

## Two independent judges: gate layers and sweep invariants

**The gate (L1–L15)** runs inside generation and is what the certificate reports.
Overall status is the worst layer (FAIL > WARN > N/A > PASS). A layer that genuinely
does not apply is N/A with an explicit reason and never counts as a pass; a layer whose
evaluator did not run is a FAIL, because an absent evaluator is not evidence of compliance.

```text
L1  Geometry & statutory        L6  Stair as computed object   L11 Terrace drainage
L2  Door swings                 L7  Vastu (advisory)           L12 Structural
L3  Bathroom clearances         L8  Program intent             L13 Accessibility
L4  Furniture clearances        L9  Ventilation                L14 Fire & egress
L5  Naming honesty              L10 Wet-core & plumbing        L15 Programme completeness
```

**The sweep** (`backend/scripts/qa_invariant_sweep.py`) is deliberately independent of the
gate: it measures the returned payload from outside and shares no code with the layer
evaluators, so agreement between the two means something.

| Invariant | Judges |
|:--|:--|
| I1 relations | forbidden wall / door-facing / above pairs, straight from the ontology |
| I2 minima | room area and width against `SpaceTypeSpec`, gross and clear |
| I3 egress | BFS connectivity, travel distance, core continuity, T4 chain |
| I4 land | anonymous slivers, wedge labels, circulation band, coverage versus cap |
| I5 identity | label == schedule == SVG == model, naming honesty |
| I6 determinism | same seed and inputs → byte-identical payload |
| I7 schemes | three ranked alternatives, materially different, honest deltas |
| I8 layers | gate present, ventilation zero-miss, furniture, certificate |
| I9 typology | returned rooms carry the requested typology's programme |
| I10 refusal | a refused brief is refused honestly, with a FAIL gate and no invented rooms |

## Certification, declines and remediation

A plan is one of three things, and the vocabulary is single-sourced in
`services/plan_verdict.py` so the screen, the print view and the PDF cannot
answer differently:

- **CERTIFIED** — statutory and safety layers PASS, zero unlisted breaches, and
every quality deviation sits inside its declared cap *and* is listed. Listed
within-cap relaxations are still printed on page 1 and in the UI ledger; they do
not withhold the certificate.
- **NOT-CERTIFIED-FAIL-STAMP** — a statutory FAIL, an unlisted breach, or a
deviation beyond its cap.
- **DECLINED** — the brief is not plausible or the gate withheld the certificate;
no plan is invented to fill the gap.

The `CERTIFIED_DEFINITION` string is the legend the UI and the PDF print verbatim
(pinned by `tests/test_plan_verdict_parity.py`), and the same suite pins the three
truth-label headings and their counts across `plan_verdict.py` and
`frontend/src/services/warningReport.ts`.

### The escalation ladder (S0–S5)

When the as-requested plan fails, `floorplan/strategy_escalation.py` tries an
ordered ladder on the same request — at most six solves including S0 — and
returns the first **fully certified** plan, or the best measured attempt when
none certifies. A strategy only succeeds when its own verdict is CERTIFIED with
a valid certificate, zero certificate failures and a PASS/WARN gate under the
calibrated verdict definition; the ladder never weakens a gate.

| Step | Lever |
|:--|:--|
| S0 | as requested |
| S1 | T2 service-row depth variant, kitchens moved into the service strip |
| S2 | count-preserving two-storey dwellings (V3): four floor-level units per plate, paired across storeys so an eight-household brief stays eight households |
| S3 | coverage-headroom trial; the feasible plate is re-measured and no growth is claimed when setbacks bind |
| S4 | storey addition inside the 4-storey engine cap |
| S5 | **not implemented for T2**; the chain reports it skipped and removes no room |

Every tried strategy stays public: the chain is attached to the plan, written as
a `STRATEGY-CHAIN` line in the warning ledger (therefore on page 1 of the PDF) and
rendered as a chip in the UI. A tried-and-failed step remains in the chain as
evidence rather than being erased. Dry-runs are memoised on the complete
canonical request (including units per floor and response-affecting options),
so a cached attempt is the same deterministic plan for the same effective
request, and the solve budget stays bounded.

`partition_variant` accepts `service_row`, `single_unit` and `duplex`; omitting it
keeps the default side-by-side two-unit plate. `duplex` requires an even number of
storeys and four floor-level units per plate (omitted or `4`); a three-unit T2
request is still refused with its named 422. `single_unit` remains the separate,
confirmation-gated dwelling-deficit remediation (`S2_deficit`), not the ladder's
S2.

### V3 duplex layout and plate policy

The V3 partitioner has two deterministic layouts. The **core-band** row layout
puts two units north and two south of a central 3.59 m core band; every unit gets
a full-depth service strip (bath, private stair, kitchen) and a 3.69–3.73 m main
room. Its minimum legal plate is about 9.7 × 17.6 m. The **compact** quadrant
layout is the guarded quadrant fallback: it is retained for sites that cannot hold the
row plate, and it fails its own room minima rather than being relabelled.

When the request is explicitly `duplex` (or the ladder's S2 patches it), the
engine may grow the plate only inside the same setback buildable and coverage
ceiling. The growth is disclosed as `DUPLEX-PLATE` with the old and new rectangle,
area delta, coverage/depth/width headroom, why it is feasible, and the binding
constraints. A site whose legal ceiling is below the row minimum keeps the
compact plan and reports the shortfall; no coverage ratio, setback or catalogue
minimum is relaxed to manufacture a plate.

V3 is **single-entry**: the lower level owns the common-corridor door and the
upper level is reached only through the aligned internal stair pair. The upper
stair enters the reachability certificate as a vertical portal seeded from the
lower stair's measured travel distance, so it is not a sealed box and not a
second corridor-accessible flat. The internal stair is validated as an aligned
1.20 × 3.31 m envelope against the `unit_stair` catalogue; tread, riser, landing,
headroom, flight continuity and handrail geometry are **not modelled**, and the
`UNIT-STAIR-02` warning states that partial scope rather than claiming stair-code
compliance.

A certified row plate measures its compliance from the wall-deducted room
schedule, not the nominal rectangles: on the 18 × 24 m case the eight households
retain sixteen level-units, the living face is 5.31 × 3.44 m clear, the bath is
1.24 m clear and the kitchen is 9.50 m². The compact 12 × 18 m target still fails
NBC-01 with the same named bath/living shortfalls it has always disclosed.

### Declines and remediation

`floorplan/plausibility.py` classifies site/programme plausibility against the
typology's minimum site area. An implausible brief is declined with named reasons
and options instead of a certificate, and every declined case in the honesty
matrix names its blocker.

Remediation cards (`floorplan/remediation.py`) carry measured numbers from the
same cached dry-runs, label the already-selected strategy as `current` rather than
offering it, and never imply certification. An S2 plan that reduces the dwelling
count is drawn only after an explicit confirmation of the deficit; until then it
stays a card and never becomes the active generation.

## Verifying it yourself

```bash
cd backend

# Land-use baseline across the golden matrix (read-only, no engine patching)
python scripts/space_engine_baseline.py

# Adversarial invariant sweep: 4 typologies x 7 plots x storeys x strictness
python scripts/qa_invariant_sweep.py --quick

# One case, with its full register
python scripts/qa_invariant_sweep.py --only T3-rect-20x20-F2

# The sweep is also a standing test: two pinned reproductions run in every pytest run
python -m pytest tests/test_invariant_sweep_standing.py -q
```

The sweep is occurrence-level on purpose: each violation is stamped with its case id,
seed and payload so it can be pinned as a regression test. Room minima dominate the
register, which is why they are counted individually rather than collapsed into one bug.

## Current status

Stated plainly, because a certificate nobody audits is decoration:

- The backend suite is green (**1,352 passed, 1 skipped**), including the standing
  sweep tests and the cross-process determinism matrix.
- The 56-case market-mix matrix (rect and near-rect plates, 12 × 15 to 40 × 60 m,
  typology-default programmes, 1–3 storeys) certifies **30 of 49 plausible cases
  (61.2%)**: T1 14/14, T2 10/14, T3 2/13, T4 4/8. All 7 implausible briefs are
  declined with named reasons, and no implausible brief is certified.
- The invariant sweep reports **0 true failures**; its 2,000 disclosed entries are
  occurrence-level relaxations carried in the payload, not gate failures.
- On the canonical 12 × 15 T2 plate the compact pocket plan puts every unit room at
  or above its catalogue **gross** minimum (living 21.98 / 17.20 m², bedroom
  10.77 / 11.53 m², kitchen 8.08 / 8.04 m², bathroom 6.70 / 6.82 m²), and the
  mathematical certificate is valid with **0 failures**.
- That plate cannot hold the full programme: 108.0 m² of buildable plate against
  122.7 m² demanded leaves six rooms below minimum, so the plan is drawn with a
  **NOT-CERTIFIED-FAIL-STAMP** verdict and an L1 WARN. The two reasons name the
  blocker and carry the options — `PLATE-SHORT` (12.0% short; service rooms bind)
  and `PROGRAMME-DEFICIT` (add a storey, reduce the programme, or enlarge the plate
  where the site allows). The five remaining sweep entries on this case are
  **clear-dimension** I2 items the 9.60 × 11.25 m plate cannot recover without
  pushing another room below its floor; they are disclosed as `ROOM-MIN` /
  `ROOM-MAX` warnings rather than hidden.
- Aspect-ratio and minima overruns produced by a legal but tight plate remain a
  known open item, not a passing check.

## Navigation
- **Previous:** [← Blueprint Engine](blueprint-engine.md)
- **Next:** [Map & Data Providers →](map-and-data.md)
