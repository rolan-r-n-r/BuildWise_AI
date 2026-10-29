"""Land economics: programme fit, residual absorption, efficiency.

The report is computed from the solved building and canonical site plan.  It
absorbs every residual polygon >= 1.0 m² into a labelled wedge or service room,
and repairs rectangular interior gaps before the wall graph/gate run.  All other
geometry is read-only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from app.schemas.land_economics import (
    LandEconomicsCertificate,
    LandEconomicsReport,
    ResidualSliver,
)
from app.schemas.multi_floor_plan import MultiStoreyBuildingModel
from app.schemas.site_plan import SitePlanModel, WedgeZone

RESIDUAL_THRESHOLD_M2 = 1.0


def _poly(coords: Sequence[Sequence[float]]) -> Optional[Polygon]:
    try:
        if len(coords) < 3:
            return None
        poly = Polygon([(float(x), float(y)) for x, y in coords])
        if not poly.is_valid:
            poly = poly.buffer(0)
        return None if poly.is_empty else poly
    except Exception:
        return None


def _footprint_poly(site_plan: SitePlanModel) -> Optional[Polygon]:
    fp = site_plan.footprint
    parts = []
    for wing in getattr(fp, "wings", []) or []:
        parts.append(box(
            float(wing.x), float(wing.y),
            float(wing.x) + float(wing.width_m), float(wing.y) + float(wing.depth_m),
        ))
    if not parts:
        parts.append(box(
            float(fp.x), float(fp.y),
            float(fp.x) + float(fp.width_m), float(fp.y) + float(fp.depth_m),
        ))
    try:
        return unary_union(parts)
    except Exception:
        return None


def _labeled_polys(site_plan: SitePlanModel, attr: str) -> List[Polygon]:
    out: List[Polygon] = []
    for item in getattr(site_plan, attr, []) or []:
        poly = _poly(getattr(item, "polygon_coords", []) or [])
        if poly is not None:
            out.append(poly)
    return out


def _safe_area(geom: Any) -> float:
    try:
        return float(geom.area) if geom is not None and not geom.is_empty else 0.0
    except Exception:
        return 0.0


def _interior_dead_area(
    footprint: Polygon,
    site_plan: SitePlanModel,
    ground_floor: Any,
) -> float:
    """Ground-floor footprint area not covered by any placed room, >= 1 m².

    A placed terrace is assigned space.  The check measures whether a parcel
    of the footprint is accounted for, not whether it is enclosed; excluding
    terraces made every ground-floor sit-out read as a dead corner (a 3.3 x
    4.7 m balcony became 15.5 m² of "dead" plate on the T2 V2 variant).
    Terraces remain excluded from programme/GFA totals elsewhere.

    Room coordinates are plate-local; the site footprint is setback-anchored.
    Translate before measuring, exactly as the baseline harness does.
    """
    rooms = list(getattr(ground_floor, "rooms", []) or [])
    if not rooms:
        return 0.0
    off_x = float(site_plan.footprint.x)
    off_y = float(site_plan.footprint.y)
    room_boxes = [
        box(r.x + off_x, r.y + off_y,
            r.x + r.width_m + off_x, r.y + r.depth_m + off_y)
        for r in rooms
    ]
    dead = footprint.difference(unary_union(room_boxes)).intersection(footprint)
    if dead.is_empty:
        return 0.0
    total = 0.0
    for geom in (dead.geoms if hasattr(dead, "geoms") else [dead]):
        if not geom.is_empty and _safe_area(geom) >= RESIDUAL_THRESHOLD_M2:
            total += _safe_area(geom)
    return round(total, 2)


def _absorb_residuals(
    site_plan: SitePlanModel,
    buildable: Polygon,
    footprint: Polygon,
) -> Tuple[List[ResidualSliver], float, float, List[Polygon]]:
    """Label every unassigned buildable residual >= 1 m² as a planter wedge.

    Returns (slivers, absorbed_area, anonymous_area, absorbed_polygons).
    Interior dead corners are repaired inside the floor plate before this runs.
    """
    wedge_polys = _labeled_polys(site_plan, "wedge_zones")
    outdoor_polys = _labeled_polys(site_plan, "outdoor_zones")
    labelled = unary_union([footprint] + wedge_polys + outdoor_polys)
    residual = buildable.difference(labelled)
    if residual.is_empty:
        return [], 0.0, 0.0, []

    geoms = list(residual.geoms) if hasattr(residual, "geoms") else [residual]
    slivers: List[ResidualSliver] = []
    absorbed_polys: List[Polygon] = []
    absorbed_area = 0.0
    anonymous_area = 0.0
    next_idx = len(site_plan.wedge_zones) + 1

    for geom in sorted(geoms, key=lambda g: (-_safe_area(g), round(g.centroid.x, 2), round(g.centroid.y, 2))):
        if geom.is_empty or not isinstance(geom, Polygon):
            continue
        area = _safe_area(geom)
        if area < RESIDUAL_THRESHOLD_M2:
            anonymous_area += area
            continue
        minx, miny, maxx, maxy = geom.bounds
        width = round(maxx - minx, 2)
        length = round(maxy - miny, 2)
        wedge = WedgeZone(
            wedge_id=f"WDG-{next_idx:02d}",
            classification="planter",
            name="Residual Sliver Planter",
            area_sqm=round(area, 2),
            centroid=(round(geom.centroid.x, 2), round(geom.centroid.y, 2)),
            polygon_coords=[(round(x, 2), round(y, 2)) for x, y in geom.exterior.coords],
            is_enclosed_storage=False,
            is_interior_side=False,
            width_m=min(width, length),
            length_m=max(width, length),
        )
        site_plan.wedge_zones.append(wedge)
        absorbed_polys.append(geom)
        absorbed_area += area
        slivers.append(ResidualSliver(
            sliver_id=wedge.wedge_id,
            area_sqm=round(area, 2),
            centroid=wedge.centroid,
            polygon_coords=wedge.polygon_coords,
            absorbed_as="planter",
            rationale="Boundary residual absorbed as a labelled planter; no anonymous outdoor area.",
        ))
        next_idx += 1

    return slivers, round(absorbed_area, 2), round(anonymous_area, 2), absorbed_polys


def repair_interior_dead_corners(
    rooms: List[Any],
    envelope: Dict[str, float],
    *,
    plate_polygon: Optional[Polygon] = None,
    reserved_polygons: Optional[Sequence[Polygon]] = None,
    threshold_m2: float = RESIDUAL_THRESHOLD_M2,
    max_passes: int = 4,
) -> List[str]:
    """Grow rooms into rectangular unassigned strips inside the floor plate.

    The legacy partitioners leave occasional rectangular gaps at wing junctions
    (for example a 1.1 m strip beside a bathroom run).  Each gap that a room can
    absorb without overlapping anything else is closed before doors, furniture,
    the wall graph and the validation gate are generated.  Returns human-readable
    repair log lines; non-rectangular or truly unabsorbable gaps are left alone
    and surface later through the land-economics certificate.
    """
    env_w = float(envelope.get("width", 0.0) or 0.0)
    env_d = float(envelope.get("depth", 0.0) or 0.0)
    if env_w <= 0.0 or env_d <= 0.0 or not rooms:
        return []
    plate = plate_polygon if plate_polygon is not None and not plate_polygon.is_empty else box(0.0, 0.0, env_w, env_d)
    plate_bounds = plate.buffer(0.01)

    logs: List[str] = []
    for _pass in range(max_passes):
        active = [r for r in rooms if r.zone_category != "terrace"]
        if not active:
            return logs
        room_polys = [box(r.x, r.y, r.x + r.width_m, r.y + r.depth_m) for r in active]
        dead = plate.difference(unary_union(room_polys))
        # Reserved bands (open-to-sky courts, shafts, terraces) are already
        # *assigned* space, not a dead corner: exclude them before repairing.
        if reserved_polygons:
            _reserved = [p for p in reserved_polygons if p is not None and not p.is_empty]
            if _reserved:
                dead = dead.difference(unary_union(_reserved))
        if dead.is_empty:
            return logs

        changed = False
        pieces = sorted(
            (g for g in (dead.geoms if hasattr(dead, "geoms") else [dead])
             if isinstance(g, Polygon) and _safe_area(g) >= threshold_m2),
            key=lambda g: (-_safe_area(g), round(g.centroid.x, 2), round(g.centroid.y, 2)),
        )
        for gap in pieces:
            minx, miny, maxx, maxy = gap.bounds
            if abs(_safe_area(gap) - (maxx - minx) * (maxy - miny)) > 0.05:
                continue  # concave gap: do not guess a room shape

            from app.services.floorplan.ontology import ONTOLOGY
            best = None
            for room in active:
                if room.is_vertical_core:
                    continue
                rx2 = room.x + room.width_m
                ry2 = room.y + room.depth_m
                in_y = room.y >= miny - 0.02 and ry2 <= maxy + 0.02
                in_x = room.x >= minx - 0.02 and rx2 <= maxx + 0.02
                # Aspect limits come from the room's SPACE TYPE, not its solver
                # handle, which resolves to nothing for most generated rooms.
                from app.services.floorplan.identity import space_type_of
                spec = ONTOLOGY.get_space(space_type_of(room) or room.room_id)
                # Hard ontology bands only.  The old 1.30 tolerance let a repair
                # push a room past its declared aspect band, so the certificate
                # passed because the band had been widened, not because the plan
                # was right.
                max_ar = spec.max_aspect_ratio if spec is not None else 3.0
                declared_min_w = (spec.min_width_m if spec is not None else 0.0) or 0.0
                # The ontology declares one clear-width minimum (the short
                # side); it applies to either axis of the grown room.
                declared_min_d = declared_min_w
                max_w_by_ar = max_ar * room.depth_m
                max_d_by_ar = max_ar * room.width_m
                candidates = []
                if in_y and abs(room.x - maxx) <= 0.02 and room.x > minx + 0.02:
                    new_w = room.width_m + (room.x - minx)
                    if new_w <= max_w_by_ar + 1e-6:
                        candidates.append(("left", minx, room.y, new_w, room.depth_m))
                if in_y and abs(rx2 - minx) <= 0.02 and rx2 < maxx - 0.02:
                    new_w = room.width_m + (maxx - rx2)
                    if new_w <= max_w_by_ar + 1e-6:
                        candidates.append(("right", room.x, room.y, new_w, room.depth_m))
                if in_x and abs(room.y - maxy) <= 0.02 and room.y > miny + 0.02:
                    new_d = room.depth_m + (room.y - miny)
                    if new_d <= max_d_by_ar + 1e-6:
                        candidates.append(("down", room.x, miny, room.width_m, new_d))
                if in_x and abs(ry2 - miny) <= 0.02 and ry2 < maxy - 0.02:
                    new_d = room.depth_m + (maxy - ry2)
                    if new_d <= max_d_by_ar + 1e-6:
                        candidates.append(("up", room.x, room.y, room.width_m, new_d))
                for direction, new_x, new_y, new_w, new_d in candidates:
                    expanded = box(new_x, new_y, new_x + new_w, new_y + new_d)
                    if not plate_bounds.contains(expanded):
                        continue
                    # The grown room must still satisfy the ontology's declared
                    # minimum clear width/depth for its own space type.  A splayed
                    # or oversized bay is not repaired by making its short side
                    # smaller than a door swing.
                    if new_w + 1e-6 < declared_min_w or new_d + 1e-6 < declared_min_d:
                        continue
                    added = expanded.area - room.width_m * room.depth_m
                    collision = False
                    for other in active:
                        if other is room:
                            continue
                        other_poly = box(other.x, other.y, other.x + other.width_m, other.y + other.depth_m)
                        if expanded.intersection(other_poly).area > 1e-6:
                            collision = True
                            break
                    if collision or added < 0.2:
                        continue
                    if best is None or added > best[0]:
                        best = (added, room, direction, new_x, new_y, new_w, new_d)

            if best is None:
                # No room can absorb the rectangle without breaking its aspect
                # limit.  Label it as a service storage room instead of leaving
                # an anonymous hole in the plate.
                from app.schemas.multi_floor_plan import MultiFloorRoomRectangle
                floor_idx = int(getattr(active[0], "floor_index", 0))
                existing = sum(1 for r in rooms if str(r.room_id).startswith(f"storage_dead_{floor_idx}"))
                storage = MultiFloorRoomRectangle(
                    room_id=f"storage_dead_{floor_idx}_{existing + 1}",
                    room_name="Dead-Corner Storage",
                    floor_index=floor_idx,
                    x=round(minx, 2),
                    y=round(miny, 2),
                    width_m=round(maxx - minx, 2),
                    depth_m=round(maxy - miny, 2),
                    area_sqm=round((maxx - minx) * (maxy - miny), 2),
                    zone="W",
                    zone_category="service",
                    vastu_compliant=True,
                    is_vertical_core=False,
                    requires_exterior_wall=False,
                    aspect_ratio=round(max(maxx - minx, maxy - miny) / max(min(maxx - minx, maxy - miny), 0.01), 2),
                    applied_rules=["LAND-07-DEAD-CORNER-ABSORPTION"],
                )
                rooms.append(storage)
                logs.append(
                    f"LAND-07 Absorbed {_safe_area(gap):.2f} m² interior dead corner as labelled "
                    f"storage room {storage.room_id}."
                )
                changed = True
                break
            added, room, direction, new_x, new_y, new_w, new_d = best
            room.x = round(new_x, 2)
            room.y = round(new_y, 2)
            room.width_m = round(new_w, 2)
            room.depth_m = round(new_d, 2)
            room.area_sqm = round(room.width_m * room.depth_m, 2)
            room.aspect_ratio = round(max(room.width_m, room.depth_m) / max(min(room.width_m, room.depth_m), 0.01), 2)
            if "LAND-07-DEAD-CORNER-ABSORPTION" not in room.applied_rules:
                room.applied_rules.append("LAND-07-DEAD-CORNER-ABSORPTION")
            logs.append(
                f"LAND-07 Absorbed {added:.2f} m² interior dead corner into "
                f"{room.room_id} ({direction} extension)."
            )
            changed = True
            break  # recompute the plate after each growth
        if not changed:
            return logs

    return logs


def compute_land_economics(
    building: MultiStoreyBuildingModel,
    site_plan: Optional[SitePlanModel],
    *,
    program_needed_area_m2: float = 0.0,
    footprint_source: str = "coverage",
    program_aware_footprint: bool = False,
) -> LandEconomicsReport:
    if site_plan is None or not building.floors:
        _missing = (
            "LAND-08 Site plan missing: no canonical site plan / floor plate was produced, "
            "so land use cannot be certified."
        )
        return LandEconomicsReport(
            program_needed_area_m2=round(program_needed_area_m2, 2),
            footprint_source=footprint_source,
            program_aware_footprint=program_aware_footprint,
            warnings=[_missing],
            certificate=LandEconomicsCertificate(
                status="FAIL", checks={"site_plan": False}, warnings=[_missing]
            ),
        )

    buildable = _poly(site_plan.buildable_polygon_coords)
    footprint = _footprint_poly(site_plan)
    if buildable is None or footprint is None:
        _bad_geom = (
            "LAND-08 Land geometry unreadable: the site plan's buildable polygon or "
            "footprint polygon could not be reconstructed, so land use cannot be certified."
        )
        return LandEconomicsReport(
            program_needed_area_m2=round(program_needed_area_m2, 2),
            footprint_source=footprint_source,
            program_aware_footprint=program_aware_footprint,
            warnings=[_bad_geom],
            certificate=LandEconomicsCertificate(
                status="FAIL", checks={"geometry": False}, warnings=[_bad_geom]
            ),
        )

    slivers, absorbed_area, subthreshold_area, absorbed = _absorb_residuals(site_plan, buildable, footprint)

    # Recompute the labelled union after absorption.  Wedge, outdoor and
    # footprint areas are made pairwise disjoint so the report can never count
    # the same square metre twice (the historical wedge/outdoor bug).
    wedge_polys = _labeled_polys(site_plan, "wedge_zones")
    outdoor_polys = _labeled_polys(site_plan, "outdoor_zones")
    wedge_union = unary_union(wedge_polys) if wedge_polys else None
    outdoor_union = unary_union(outdoor_polys) if outdoor_polys else None
    footprint_on_site = footprint.intersection(buildable)
    wedge_on_site = (
        wedge_union.intersection(buildable).difference(footprint_on_site)
        if wedge_union is not None else Polygon()
    )
    outdoor_on_site = (
        outdoor_union.intersection(buildable).difference(footprint_on_site).difference(wedge_on_site)
        if outdoor_union is not None else Polygon()
    )
    occupied = unary_union([footprint_on_site, wedge_on_site, outdoor_on_site])
    residual_after = buildable.difference(occupied)
    residual_after_area = round(_safe_area(residual_after), 2)
    interior_dead = _interior_dead_area(footprint, site_plan, building.floors[0])

    ground = building.floors[0]
    ground_program = sum(
        r.area_sqm for r in ground.rooms
        if r.zone_category not in ("circulation", "terrace")
    )
    ground_circ = sum(r.area_sqm for r in ground.rooms if r.zone_category == "circulation")
    ground_enclosed = sum(r.area_sqm for r in ground.rooms if r.zone_category != "terrace")
    total_gfa = sum(r.area_sqm for f in building.floors for r in f.rooms if r.zone_category != "terrace")
    total_circ = sum(r.area_sqm for f in building.floors for r in f.rooms if r.zone_category == "circulation")
    buildable_area = round(float(site_plan.buildable_area_sqm), 2)
    footprint_area = round(float(site_plan.footprint.area_sqm), 2)
    plot_area = float(site_plan.plot_polygon.area_sqm)
    coverage_limit = round(plot_area * float(building.ground_coverage_ratio or 0.60), 2)
    program_deficit = max(0.0, round(float(program_needed_area_m2) - footprint_area, 2))
    eff_g = min(100.0, 100.0 * (ground_program + ground_circ) / max(buildable_area, 0.01))
    footprint_utilization = 100.0 * ground_enclosed / max(footprint_area, 0.01)
    circ_ratio = 100.0 * total_circ / max(total_gfa, 0.01)
    far = total_gfa / max(plot_area, 0.01)

    furniture_total = 0
    furniture_ok = 0
    for floor in building.floors:
        for room in floor.rooms:
            # Furnish service rooms too (locker rooms, server rooms);
            # furniture fit is measured over every room with a placed set, not
            # only public/private programme rooms.
            if room.zone_category not in ("circulation", "terrace") and room.furniture:
                furniture_total += 1
                if all(item.is_satisfied for item in room.furniture):
                    furniture_ok += 1
    furniture_fit = round(100.0 * furniture_ok / furniture_total, 1) if furniture_total else None

    warnings: List[str] = []
    if program_deficit > 0.5:
        warnings.append(
            f"LAND-01 Programme deficit: {program_needed_area_m2:.1f} m² needed vs "
            f"{footprint_area:.1f} m² footprint; shortfall {program_deficit:.1f} m². "
            "Reduce programme, raise coverage, or accept explicit consolidation."
        )
    if slivers:
        warnings.append(
            f"LAND-02 Absorbed {len(slivers)} residual region(s) totalling {absorbed_area:.1f} m² "
            "into labelled storage/planter wedges; no anonymous outdoor sliver remains above 1.0 m²."
        )
    if interior_dead >= RESIDUAL_THRESHOLD_M2:
        warnings.append(
            f"LAND-05 Interior dead corner: {interior_dead:.1f} m² of the ground footprint "
            "is not assigned to any room; resize the programme or close the gap at placement."
        )
    if circ_ratio < 12.0 or circ_ratio > 20.0:
        warnings.append(
            f"LAND-03 Circulation ratio {circ_ratio:.1f}% is outside the 12–20% target band."
        )
    if footprint_source == "inscribed" and program_deficit > 0.5:
        warnings.append(
            "LAND-06 Irregular buildable: the inscribed footprint, not the programme, "
            "is the binding constraint; the deficit needs a plot/coverage trade-off."
        )

    coverage_ratio = float(building.ground_coverage_ratio or 0.60)
    checks = {
        "site_plan_present": True,
        "footprint_contained_in_buildable": bool(site_plan.certificate.footprint_contained_in_buildable),
        "coverage_within_limit": footprint_area <= coverage_limit + 0.5,
        "program_fits_footprint": program_deficit <= 0.5,
        "circulation_within_12_20": 12.0 <= circ_ratio <= 20.0,
        "footprint_utilization_90": footprint_utilization >= 90.0,
        "anonymous_outdoor_zero": subthreshold_area < 0.5 and residual_after_area < 0.5,
        "residuals_labelled": len(slivers) == 0 or all(s.absorbed_as for s in slivers),
        "interior_dead_corners_zero": interior_dead < RESIDUAL_THRESHOLD_M2,
        "furniture_fit": furniture_fit is None or furniture_fit >= 80.0,
    }

    # NO SILENT BREACH: every failed check names itself in the
    # surfaced warnings. A check that can fail silently is a check the reader
    # cannot audit. Codes already emitted above (LAND-01/03/05) are not repeated.
    _check_messages = {
        "footprint_contained_in_buildable": (
            "LAND-09 Footprint out of bounds: the ground plate is not contained in the "
            "setback buildable polygon."
        ),
        "coverage_within_limit": (
            f"LAND-10 Ground coverage breach: footprint {footprint_area:.1f} m² exceeds the "
            f"{coverage_limit:.1f} m² cap ({plot_area:.1f} m² plot × {coverage_ratio * 100:.0f}% "
            "coverage)."
        ),
        "footprint_utilization_90": (
            f"LAND-11 Ground plate underused: rooms cover {footprint_utilization:.1f}% of the "
            f"{footprint_area:.1f} m² footprint (floor 90%)."
        ),
        "anonymous_outdoor_zero": (
            f"LAND-12 Anonymous residual: {subthreshold_area:.2f} m² in sub-threshold slivers and "
            f"{residual_after_area:.2f} m² unlabelled buildable area remain outside any labelled zone."
        ),
        "residuals_labelled": (
            f"LAND-13 Unlabelled residual: {len([s for s in slivers if not s.absorbed_as])} "
            "residual region(s) were absorbed without a labelled use."
        ),
        "furniture_fit": (
            f"LAND-14 Furniture fit {furniture_fit if furniture_fit is not None else 0.0:.1f}% "
            "is below the 80% placement target."
        ),
    }
    for _key, _message in _check_messages.items():
        if not checks.get(_key, True) and _message not in warnings:
            warnings.append(_message)

    hard_fail = not (
        checks["footprint_contained_in_buildable"]
        and checks["coverage_within_limit"]
        and checks["program_fits_footprint"]
    )
    warn = not hard_fail and not (
        checks["circulation_within_12_20"]
        and checks["footprint_utilization_90"]
        and checks["anonymous_outdoor_zero"]
        and checks["residuals_labelled"]
        and checks["interior_dead_corners_zero"]
        and checks["furniture_fit"]
    )
    status = "FAIL" if hard_fail else ("WARN" if warn else "PASS")

    return LandEconomicsReport(
        program_needed_area_m2=round(float(program_needed_area_m2), 2),
        buildable_area_sqm=buildable_area,
        coverage_limit_area_sqm=coverage_limit,
        footprint_area_sqm=footprint_area,
        footprint_source=footprint_source,
        program_aware_footprint=program_aware_footprint,
        program_deficit_sqm=program_deficit,
        ground_program_area_sqm=round(ground_program, 2),
        ground_circulation_area_sqm=round(ground_circ, 2),
        total_gfa_sqm=round(total_gfa, 2),
        land_use_efficiency_pct=round(eff_g, 2),
        footprint_utilization_pct=round(footprint_utilization, 2),
        floor_area_ratio=round(far, 2),
        circulation_ratio_pct=round(circ_ratio, 2),
        wedge_area_sqm=round(_safe_area(wedge_on_site), 2),
        outdoor_area_sqm=round(_safe_area(outdoor_on_site), 2),
        occupied_area_sqm=round(_safe_area(occupied), 2),
        waste_area_sqm=residual_after_area,
        waste_pct=round(100.0 * residual_after_area / max(buildable_area, 0.01), 2),
        anonymous_outdoor_area_sqm=round(subthreshold_area, 2),
        dead_corner_area_sqm=interior_dead,
        sliver_count=len(slivers),
        slivers=slivers,
        absorbed_residual_count=len(absorbed),
        furniture_fit_pct=furniture_fit,
        warnings=warnings,
        certificate=LandEconomicsCertificate(status=status, checks=checks, warnings=warnings),
    )
