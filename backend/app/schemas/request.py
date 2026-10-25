from typing import List, Optional, Literal
from pydantic import BaseModel, Field

from app.schemas.typology import BoundaryShapeType, BuildingSource, BuildingTypology

# ---- Map-first capture: additive boundary schema ----
class PlotVertex(BaseModel):
    """One survey vertex in the local tangent plane.

    ``NaN``/``Infinity`` are accepted by Python's json parser even though they
    are not JSON, and an infinite vertex used to reach the shoelace loop and
    then poison response serialisation with a 500.  Rejecting
    them here turns that into the normal 422 field error.
    """

    x: float = Field(..., allow_inf_nan=False, description="Local Easting in meters (+X East)")
    y: float = Field(..., allow_inf_nan=False, description="Local Northing in meters (+Y North)")


class BoundarySummary(BaseModel):
    """Client-captured site boundary (single-source model from the map wizard)."""
    vertices: List[PlotVertex] = Field(..., min_length=3, max_length=64)
    origin_lat: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    origin_lon: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    shape_type: BoundaryShapeType = Field("irregular", description="rectangle | irregular | trapezoid | l_shape | pentagon | polygon")
    area_sqm: float = Field(..., ge=0, allow_inf_nan=False)
    perimeter_m: float = Field(..., ge=0, allow_inf_nan=False)
    source: BuildingSource = Field("trace", description="trace | rectangle | preset | import | legacy")
    frontage_edge_index: Optional[int] = Field(None, ge=0)

class AnalysisRequest(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0, allow_inf_nan=False, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180.0, le=180.0, allow_inf_nan=False, description="Longitude in decimal degrees")
    built_up_area_sqft: float = Field(..., ge=500.0, le=50000.0, allow_inf_nan=False, description="Built-up area in square feet")
    quality_grade: Literal["basic", "standard", "premium"] = Field("standard", description="Construction quality specification")
    building_typology: BuildingTypology = Field("residential_single", description="Building typology identifier")
    floors: int = Field(1, ge=1, le=4, description="Number of above-ground floors")
    ai_provider: Optional[Literal["mock", "groq", "gemini", "ollama"]] = Field("mock", description="AI provider: mock, groq, gemini, ollama")
    override_land_rate_per_sqft: Optional[float] = Field(None, ge=10.0, le=500000.0, allow_inf_nan=False, description="Optional user-supplied land rate override in INR per sq ft")
    plot_area_sqft: Optional[float] = Field(None, ge=200.0, le=100000.0, allow_inf_nan=False, description="Site plot area in sq ft; derived from ground coverage if omitted")
    ground_coverage_ratio: Optional[float] = Field(0.60, ge=0.40, le=0.75, allow_inf_nan=False, description="Ground coverage ratio for plot area derivation (0.40 to 0.75, default 0.60)")
    client_requirements: Optional[str] = Field(None, max_length=240, description="Optional user requirements / client notes")
    boundary: Optional[BoundarySummary] = Field(None, description="Optional map-captured site boundary (single-source model)")

class ReportRequest(BaseModel):
    analysis_data: dict = Field(..., description="Complete AnalysisResponse payload for PDF compilation")
    site_vision: Optional[dict] = Field(None, description="Optional SiteVisionResponse object")
    floor_plan: Optional[dict] = Field(None, description="Optional FloorPlanResponse object")

