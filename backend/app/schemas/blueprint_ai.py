"""
blueprint_ai.py — Schemas for AI-Powered Blueprint Plan Warning Analysis and Advisory.
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class AIWarningDetail(BaseModel):
    original_warning: str = Field(..., description="Verbatim original deterministic warning text")
    warning_id: Optional[str] = Field(None, description="Extracted code identifier, e.g., FAIL-L4, PROP-DIM-01, NBC")
    category: str = Field(..., description="Categorization: Critical Issues, Structural & Engineering, Building Code & Compliance, Architectural & Layout, Space & Dimension, Circulation & Accessibility, Optimization Opportunities")
    severity: str = Field(..., description="Deterministic severity: critical, high, moderate, advisory")
    ai_priority: str = Field(default="medium", description="Recommended priority: critical, high, medium, low, optimization")
    explanation: str = Field(..., description="Clear plain-English explanation of what this warning means")
    why_it_matters: str = Field(..., description="Why this issue matters in construction and spatial functionality")
    potential_risk: str = Field(..., description="Potential consequences if left unresolved")
    suggested_correction: str = Field(..., description="Actionable recommendation to resolve or improve the condition")
    affected_element: Optional[str] = Field(None, description="Specific room, corridor, core, or structural element affected")
    requires_professional_review: bool = Field(default=False, description="Whether this issue mandates review by a licensed structural engineer or architect")
    related_warning_ids: List[str] = Field(default_factory=list, description="IDs of related warnings sharing the same context")


class BlueprintGroupedIssue(BaseModel):
    group_name: str = Field(..., description="Descriptive title of the shared issue")
    underlying_cause: str = Field(..., description="Underlying architectural or spatial cause connecting the warnings")
    related_warnings: List[str] = Field(default_factory=list, description="List of related warning strings or IDs")
    combined_solution: str = Field(..., description="Single cohesive design modification that addresses multiple warnings")


class BlueprintPrioritizedAction(BaseModel):
    priority: str = Field(..., description="Action urgency: Critical, High, Medium, Low, Optimization")
    action_title: str = Field(..., description="Concise action heading")
    description: str = Field(..., description="Step-by-step guidance on implementing the corrective design change")
    target_elements: List[str] = Field(default_factory=list, description="Rooms, walls, or zones to modify")
    original_severity: str = Field(default="moderate", description="Original underlying severity")


class BlueprintAssessment(BaseModel):
    ready_for_review: bool = Field(..., description="Whether the blueprint meets statutory baseline to proceed to detailed design review")
    overall_status_summary: str = Field(..., description="Holistic summary of the plan's architectural and geometric health")
    key_concerns: List[str] = Field(default_factory=list, description="Primary structural, safety, or functional bottlenecks")
    recurring_themes: List[str] = Field(default_factory=list, description="Patterns appearing across multiple rooms or storeys")
    professional_review_required: bool = Field(default=True, description="Whether professional structural/architectural sign-off is required")
    next_steps: List[str] = Field(default_factory=list, description="Ordered recommended actions for the designer")


class BlueprintAIAnalysisResponse(BaseModel):
    blueprint_assessment: BlueprintAssessment
    categorized_warnings: Dict[str, List[AIWarningDetail]] = Field(default_factory=dict)
    grouped_issues: List[BlueprintGroupedIssue] = Field(default_factory=list)
    prioritized_actions: List[BlueprintPrioritizedAction] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)


class BlueprintAIAnalysisRequest(BaseModel):
    warnings: List[str] = Field(default_factory=list, description="List of warning strings from the floor plan generator")
    plan_verdict: Optional[str] = Field(None, description="Overall deterministic plan verdict, e.g., NOT-CERTIFIED-FAIL-STAMP, ADVISORY, CERTIFIED")
    mathematical_certificate: Optional[Dict[str, Any]] = Field(None, description="Mathematical validity certificate payload")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Floor plan calculated metrics")
    unmet_requirements: Optional[List[Dict[str, Any]]] = Field(None, description="Unplaced rooms or unmet constraints")
    building_typology: Optional[str] = Field("residential_single", description="Building typology")
    built_up_area_sqft: Optional[float] = Field(None, description="Target built up area")
    floors: Optional[int] = Field(1, description="Number of storeys")
    ai_provider: Optional[str] = Field(None, description="Requested AI provider (byok or deterministic)")
    ai_model: Optional[str] = Field(None, description="Requested AI model")
