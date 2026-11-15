from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Project or site title")
    description: Optional[str] = Field(default=None, max_length=1000, description="Optional project notes")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude (WGS84)")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude (WGS84)")
    formatted_address: Optional[str] = Field(default=None, description="Human-readable reverse-geocoded location")
    building_typology: Optional[str] = Field(default=None, description="Building typology identifier")
    floors: Optional[int] = Field(default=None, ge=1, le=100, description="Configured floor count")
    built_up_area_sqft: Optional[float] = Field(default=None, ge=0, description="Built-up area in square feet")
    composite_score: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Composite feasibility score")
    total_cost_inr: Optional[float] = Field(default=None, ge=0, description="Estimated total project expenditure")
    is_bookmarked: bool = Field(default=False, description="Whether project is starred/favorited")
    boundary: Optional[Dict[str, Any]] = Field(default=None, description="Captured plot boundary / GeoJSON")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Analysis input parameters")
    analysis_summary: Optional[Dict[str, Any]] = Field(default=None, description="High-level summary indicators")
    analysis_data: Optional[Dict[str, Any]] = Field(default=None, description="Full analysis response")
    floor_plan_data: Optional[Dict[str, Any]] = Field(default=None, description="Generated floor plan response")
    site_vision_data: Optional[Dict[str, Any]] = Field(default=None, description="Site vision response")


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    is_bookmarked: Optional[bool] = None


class ProjectSummary(BaseModel):
    id: str
    user_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    latitude: float
    longitude: float
    formatted_address: Optional[str] = None
    building_typology: Optional[str] = None
    floors: Optional[int] = None
    built_up_area_sqft: Optional[float] = None
    composite_score: Optional[float] = None
    total_cost_inr: Optional[float] = None
    is_bookmarked: bool
    created_at: str
    updated_at: str


class ProjectDetail(ProjectSummary):
    boundary: Optional[Dict[str, Any]] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    analysis_summary: Optional[Dict[str, Any]] = None
    analysis_data: Optional[Dict[str, Any]] = None
    floor_plan_data: Optional[Dict[str, Any]] = None
    site_vision_data: Optional[Dict[str, Any]] = None


class ProjectListResponse(BaseModel):
    items: List[ProjectSummary]
    total: int
