from app.services.cost_service import calculate_construction_cost

def test_cost_base_rates():
    cost_basic = calculate_construction_cost(area_sqft=1000.0, quality_grade="basic", slope_pct=2.0)
    assert cost_basic.base_rate_per_sqft == 1500.0
    assert cost_basic.base_cost_inr == 1500000.0
    assert cost_basic.terrain_multiplier == 1.0

    cost_standard = calculate_construction_cost(area_sqft=1000.0, quality_grade="standard", slope_pct=2.0)
    assert cost_standard.base_rate_per_sqft == 2200.0
    assert cost_standard.base_cost_inr == 2200000.0

    cost_premium = calculate_construction_cost(area_sqft=1000.0, quality_grade="premium", slope_pct=2.0)
    assert cost_premium.base_rate_per_sqft == 3500.0
    assert cost_premium.base_cost_inr == 3500000.0

def test_cost_terrain_multiplier():
    cost_flat = calculate_construction_cost(area_sqft=1000.0, quality_grade="standard", slope_pct=2.0)
    assert cost_flat.terrain_multiplier == 1.0
    assert cost_flat.terrain_surcharge_inr == 0.0

    cost_steep = calculate_construction_cost(area_sqft=1000.0, quality_grade="standard", slope_pct=20.0)
    assert cost_steep.terrain_multiplier == 1.18
    assert cost_steep.terrain_surcharge_inr > 0.0
    assert cost_steep.total_estimated_cost_inr > cost_flat.total_estimated_cost_inr

def test_cost_breakdown_proportions():
    cost = calculate_construction_cost(area_sqft=2000.0, quality_grade="standard", slope_pct=4.0)
    assert len(cost.breakdown) == 5
    total_pct = sum(item.percentage for item in cost.breakdown)
    assert 99.0 <= total_pct <= 101.0
    assert cost.cost_range_min_inr < cost.total_estimated_cost_inr < cost.cost_range_max_inr

def test_steep_slope_contingency_guaranteed():
    """Ensure statutory contingency reserve is never zeroed out even on steep terrain (>25% slope)."""
    cost_steep = calculate_construction_cost(area_sqft=2000.0, quality_grade="standard", slope_pct=28.0)
    contingency = next(item for item in cost_steep.breakdown if "Contingency" in item.category)
    assert contingency.amount_inr > 0.0
    assert 8.0 <= contingency.percentage <= 10.0
    total_pct = sum(item.percentage for item in cost_steep.breakdown)
    assert 99.0 <= total_pct <= 101.0
