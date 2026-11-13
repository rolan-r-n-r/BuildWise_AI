from typing import List
from app.schemas.response import CostEstimate, CostItem

# Benchmark Plinth Area Rates (CPWD Inspired) in INR per square foot
BASE_RATES = {
    "basic": 1500.0,
    "standard": 2200.0,
    "premium": 3500.0
}

def calculate_construction_cost(
    area_sqft: float,
    quality_grade: str,
    slope_pct: float,
    floors: int = 1
) -> CostEstimate:
    """
    Computes preliminary construction cost estimation using CPWD-aligned plinth area rates,
    adjusted for quality grade, topography slope, and multi-floor vertical distribution.
    """
    grade_key = quality_grade.lower() if quality_grade.lower() in BASE_RATES else "standard"
    base_rate = BASE_RATES[grade_key]

    # Floor factor: Additional structural column/slab allowance for multi-storey
    floor_factor = 1.0 + (floors - 1) * 0.04  # 4% structural reinforcement increase per additional floor

    # Terrain slope adjustment multiplier
    if slope_pct <= 3.0:
        terrain_mult = 1.00
    elif slope_pct <= 8.0:
        terrain_mult = 1.05
    elif slope_pct <= 15.0:
        terrain_mult = 1.10
    elif slope_pct <= 25.0:
        terrain_mult = 1.18
    else:
        terrain_mult = 1.25

    base_cost = round(area_sqft * base_rate * floor_factor, 2)
    surcharge_cost = round(base_cost * (terrain_mult - 1.0), 2)
    subtotal = base_cost + surcharge_cost

    # Standard CPWD cost distribution proportions
    civil_structural_pct = 0.50
    finishes_pct = 0.18
    mep_pct = 0.14
    # Statutory contingency reserve is guaranteed at 8-10% of subtotal;
    # grading preparation scales with terrain slope without zeroing contingency.
    contingency_pct = max(0.08, round(0.10 - (terrain_mult - 1.0) * 0.08, 3))
    grading_prep_pct = round(1.0 - (civil_structural_pct + finishes_pct + mep_pct + contingency_pct), 3)

    civil_amt = round(subtotal * civil_structural_pct, 2)
    finishes_amt = round(subtotal * finishes_pct, 2)
    mep_amt = round(subtotal * mep_pct, 2)
    grading_amt = round(subtotal * grading_prep_pct, 2)
    contingency_amt = round(subtotal - (civil_amt + finishes_amt + mep_amt + grading_amt), 2)

    total_cost = round(civil_amt + finishes_amt + mep_amt + grading_amt + contingency_amt, 2)
    min_cost = round(total_cost * 0.925, 2)
    max_cost = round(total_cost * 1.075, 2)

    breakdown: List[CostItem] = [
        CostItem(
            category="Civil & Structural Framework",
            amount_inr=civil_amt,
            percentage=round(civil_structural_pct * 100.0, 1),
            description="Reinforced concrete footings, grade beams, columns, floor slabs, and load-bearing masonry."
        ),
        CostItem(
            category="Architectural Finishes",
            amount_inr=finishes_amt,
            percentage=round(finishes_pct * 100.0, 1),
            description="Vitrified tile flooring, internal gypsum plaster, exterior weather-coat paint, doors, and glazed fenestrations."
        ),
        CostItem(
            category="MEP & Building Services",
            amount_inr=mep_amt,
            percentage=round(mep_pct * 100.0, 1),
            description="Concealed electrical conduit wiring, distribution boards, CPVC sanitary plumbing, drainage fittings, and stormwater piping."
        ),
        CostItem(
            category="Site Grading & Substructure Prep",
            amount_inr=grading_amt,
            percentage=round(grading_prep_pct * 100.0, 1),
            description=f"Site excavation, cut-and-fill levelling, anti-termite treatment, compaction, and retaining provisions (Terrain modifier: {terrain_mult}x)."
        ),
        CostItem(
            category="Statutory Approvals & Contingency",
            amount_inr=contingency_amt,
            percentage=round((contingency_amt / total_cost) * 100.0, 1),
            description="Municipal plan sanctions, structural peer review, material batch testing, and unexpected site variances (8-10%)."
        )
    ]

    disclaimer = (
        "Preliminary estimate based on CPWD Plinth Area Rates benchmarks for Indian construction conditions. "
        "Excludes land acquisition costs, statutory GST, luxury interior cabinetry, and specialized deep piling. "
        "Final tender cost will vary based on geotechnical soil report and detailed structural drawings."
    )

    return CostEstimate(
        base_rate_per_sqft=base_rate,
        terrain_multiplier=terrain_mult,
        base_cost_inr=base_cost,
        terrain_surcharge_inr=surcharge_cost,
        total_estimated_cost_inr=total_cost,
        cost_range_min_inr=min_cost,
        cost_range_max_inr=max_cost,
        breakdown=breakdown,
        currency="INR",
        disclaimer=disclaimer
    )
