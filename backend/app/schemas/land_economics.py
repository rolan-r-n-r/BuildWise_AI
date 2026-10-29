"""Land-economics report and SPACE-EFFICIENCY certificate."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class ResidualSliver(BaseModel):
    sliver_id: str
    area_sqm: float
    centroid: Tuple[float, float]
    polygon_coords: List[Tuple[float, float]] = Field(default_factory=list)
    absorbed_as: str = "planter"
    rationale: str = ""


class LandEconomicsCertificate(BaseModel):
    status: str = "PASS"  # PASS | WARN | FAIL
    checks: Dict[str, bool] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class LandEconomicsReport(BaseModel):
    """Program-aware land use, footprint fit, residuals and efficiency."""

    program_needed_area_m2: float = 0.0
    buildable_area_sqm: float = 0.0
    coverage_limit_area_sqm: float = 0.0
    footprint_area_sqm: float = 0.0
    footprint_source: str = "coverage"  # coverage | program | inscribed
    program_aware_footprint: bool = False
    program_deficit_sqm: float = 0.0
    ground_program_area_sqm: float = 0.0
    ground_circulation_area_sqm: float = 0.0
    total_gfa_sqm: float = 0.0
    land_use_efficiency_pct: float = 0.0  # usable-area efficiency, ground floor
    footprint_utilization_pct: float = 0.0
    floor_area_ratio: float = 0.0
    circulation_ratio_pct: float = 0.0
    wedge_area_sqm: float = 0.0
    outdoor_area_sqm: float = 0.0
    occupied_area_sqm: float = 0.0
    waste_area_sqm: float = 0.0
    waste_pct: float = 0.0
    anonymous_outdoor_area_sqm: float = 0.0
    dead_corner_area_sqm: float = Field(
        default=0.0,
        description="Ground-floor footprint area not covered by any room, counting regions >= 1 m²",
    )
    sliver_count: int = Field(
        default=0,
        description="Residual site regions >= 1 m² found and labelled as wedge zones",
    )
    slivers: List[ResidualSliver] = Field(default_factory=list)
    absorbed_residual_count: int = Field(
        default=0,
        description="Residual regions converted into labelled wedge zones",
    )
    furniture_fit_pct: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)
    certificate: LandEconomicsCertificate = Field(default_factory=LandEconomicsCertificate)


def compute_program_needed_area(engine: object) -> float:
    """Programme + walls + circulation area required by the largest floor.

    This is deliberately computed from the ontology catalogue (minimum carpet
    areas), not from the geometry that was already produced, so the footprint
    is never sized by its own output.
    """
    from app.services.floorplan.constrained_solver import expand_program
    from app.services.floorplan.wall_graph import compute_stair_geometry

    total_storeys = max(1, int(getattr(engine, "total_storeys", 1)))
    typology = getattr(engine, "typology", "T1_SINGLE_FAMILY")
    profile = getattr(engine, "profile", None)
    floor_height = float(getattr(profile, "floor_height_m", 3.0) or 3.0)
    stair = compute_stair_geometry(floor_height_m=floor_height, typology=typology)
    core_area = float(stair.stair_box_width_m) * float(stair.stair_box_depth_m)
    if typology in ("T2_FAMILY_APARTMENT", "T3_LARGE_COMPLEX"):
        core_area += 3.24  # passenger lift
    if typology == "T3_LARGE_COMPLEX":
        core_area += 3.0  # secondary egress stair allowance

    worst = 0.0
    for z in range(total_storeys):
        rooms = expand_program(engine, z)
        if not rooms:
            continue
        if typology == "T1_SINGLE_FAMILY":
            # Two minima sources exist: the T1 programme spec (living 16,
            # kitchen 7.5, dining 8) and the placement catalogue the validator
            # audits against (18, 9, 9). Sizing the plate on the looser one
            # under-built it and manufactured ROOM-MIN breaches the layout
            # could never avoid. Size on the stricter one; rooms with no
            # catalogue row (a foyer) keep the programme's own minimum.
            from app.services.floorplan.grid_model import get_explicit_room_catalog_entry

            program = sum(
                max(
                    float(r.spec.min_area_sqm),
                    float(
                        (get_explicit_room_catalog_entry(r.instance_id) or {}).get(
                            "catalog_min_m2"
                        )
                        or 0.0
                    ),
                )
                for r in rooms
            )
        else:
            program = sum(float(r.spec.min_area_sqm) for r in rooms)
        circulation = max(8.0, program * 0.14)
        walls = program * 0.08
        worst = max(worst, program + circulation + walls + core_area)

    # T1 is a banded plan: three fixed bands (living face / stair + circulation
    # / service row). A plate sized on the raw room minima alone is too shallow
    # for those bands - it lands the service row at 2.6 m and the living face
    # below 3.6 m. Model the BAND-CAPACITY floor instead: the widths each band
    # needs at its statutory depth, times their summed depth. This is the size
    # at which the partition can actually honour the catalogue.
    # A band-capacity plate is only meaningful when the SITE can contain it.
    # On a plot whose statutory ceiling is below the band plate (a 10 x 12 m
    # plot at 60 % ceilings at 72 m2 against a 87.9 m2 band plate), quoting the
    # band figure as "need" manufactures an unavoidable LAND deficit and a
    # refusal for a brief the partitioner can still draw in degraded form.
    # Cap the model by the same ceiling the solver will apply.
    _plot_w = float(getattr(engine, "plot_w", 0.0) or 0.0)
    _plot_d = float(getattr(engine, "plot_d", 0.0) or 0.0)
    _coverage = float(getattr(engine, "coverage", 0.6) or 0.6)
    _avail_w = max(4.0, _plot_w - 2 * max(1.0, min(2.0, _plot_w * 0.10)))
    _front = max(1.8, min(3.5, _plot_d * 0.15))
    _rear = max(1.2, min(2.5, _plot_d * 0.10))
    _avail_d = max(4.0, _plot_d - _front - _rear)
    _ceil_est = min(_avail_w * _avail_d, _plot_w * _plot_d * _coverage) \
        if _plot_w > 0 and _plot_d > 0 else 0.0

    # The band model assumes a RECTANGULAR plate: three full-width rows.  An
    # irregular boundary is decomposed into wings and an inscribed rectangle,
    # where the band widths cannot be guaranteed; quoting the band area there
    # grew the L-shaped 15 x 18 m T1 plate from 101.0 to 108.4 m2 and narrowed
    # the master bedroom to 2.70 m clear (two cases that used to certify).
    # Rectilinear plates (the population the model was built for) keep it.
    _rectilinear_plot = True
    _poly = getattr(engine, "req", None)
    _poly = getattr(_poly, "plot_polygon", None) if _poly is not None else None
    if _poly is not None and not getattr(_poly, "is_regular_rectangle", True):
        _rectilinear_plot = False

    band_worst = 0.0
    if typology == "T1_SINGLE_FAMILY" and _rectilinear_plot:
        for z in range(total_storeys):
            rooms = expand_program(engine, z)
            if not rooms:
                continue
            ids = {r.spec.id for r in rooms}
            front_w = 18.0 / 3.60
            if "puja" in ids:
                front_w += 2.00 / 1.0
            if "foyer" in ids:
                front_w += 1.50 / 1.0
            mid_w = float(stair.stair_box_width_m) + 2.00
            if "dining" in ids:
                mid_w += 9.0 / float(stair.stair_box_depth_m)
            if "utility" in ids:
                mid_w += 3.0 / float(stair.stair_box_depth_m)
            third_area = 14.0 if "master_bed" in ids else 10.0
            south_w = 1.50 + third_area / 3.40
            if "kitchen" in ids:
                south_w += 9.0 / 3.40
            band_w = max(front_w, mid_w, south_w, 4.0)
            band_worst = max(
                band_worst, band_w * (3.60 + float(stair.stair_box_depth_m) + 3.40)
            )
    # A band plate cannot be wider than the setback buildable.  On an 8 x 40 m
    # plot the 4-room band model asks for 8.26 m of frontage inside a 6.0 m
    # buildable, and the un-capped need deepened the plate until the service row
    # (bath 1.70 x 4.81 = 1:2.83) fell just past its relaxation cap.  The
    # capacity model describes a plate the site can hold; excess programme is a
    # deficit the partitioner discloses, not extra depth.
    # The cap only applies while the frontage is SHORT, not absent: on a 6 x 24 m
    # plot the buildable is 4.0 m, the band frontage is 2.07x wider, no band can
    # form at any depth, and shrinking the need to the 4 m band plate (41 m2)
    # sized a 68 m2 plate that collapsed the kitchen.  There the uncapped
    # programme area governs and the partitioner degrades the rows instead.
    if band_worst > 0.0 and _avail_w > 0.0:
        _band_w = band_worst / (3.60 + float(stair.stair_box_depth_m) + 3.40)
        if _band_w <= _avail_w * 1.5:
            band_worst = min(
                band_worst, _avail_w * (3.60 + float(stair.stair_box_depth_m) + 3.40)
            )
    if band_worst > 0.0 and _ceil_est > 0.0 and band_worst > _ceil_est + 0.5:
        # The site cannot host the band plate at all (a 10 x 10 m plot at 60 %
        # ceilings at 56 m2 against an 85 m2 band plate).  Quoting the band
        # figure as "need" manufactured a 34 % land deficit and refused a brief
        # the partitioner draws every day; the site's own room-minima need
        # governs and the tight plate is disclosed through ROOM-MIN/L16.
        band_worst = 0.0
    return round(max(worst, band_worst, 30.0), 2)
