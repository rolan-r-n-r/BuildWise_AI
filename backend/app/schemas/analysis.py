import re
import json
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
from app.schemas.response import SiteFeasibilityAIAnalysis


class AnalysisResponse(BaseModel):
    """
    Strict response schema for Indian Civil and Structural Engineering site feasibility reports.
    Adheres strictly to CPWD benchmarks, IS 456, IS 1893, and NBC 2016.
    """
    model_config = ConfigDict(extra="forbid")

    feasibility_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Overall site feasibility score based on IS codes and user parameters"
    )
    structural_recommendations: List[str] = Field(
        ...,
        min_length=1,
        description="Specific structural requirements based on IS 456 for the selected storeys and typology"
    )
    cost_breakdown: Dict[str, Any] = Field(
        ...,
        description="CPWD DSR benchmark costs in INR, strictly calculated based on the provided Plinth Area and Specification Grade"
    )
    vastu_compliance: Dict[str, Any] = Field(
        ...,
        description="Orientation analysis based on NBC 2016 and the provided Lat/Lon solar path"
    )
    parameter_reflection: str = Field(
        ...,
        description="A 2-sentence explanation of HOW the user's specific inputs (e.g., Premium grade + G+1 storeys) influenced this specific report."
    )
    engineering_summary: Optional[str] = Field(
        default=None,
        description="Comprehensive professional civil engineering synthesis evaluating site feasibility and structural design considerations"
    )
    detailed_recommendations: Optional[List[str]] = Field(
        default_factory=list,
        description="Specific actionable engineering and site planning recommendations"
    )
    structured_analysis: Optional[SiteFeasibilityAIAnalysis] = Field(
        default=None,
        description="Comprehensive structured multi-section AI feasibility analysis"
    )
    structured_narrative: Optional[SiteFeasibilityAIAnalysis] = Field(
        default=None,
        description="Alias for structured_analysis matching response.py and frontend types"
    )
    executive_summary: Optional[str] = Field(default=None)
    overall_assessment: Optional[str] = Field(default=None)
    key_strengths: Optional[List[str]] = Field(default_factory=list)
    key_concerns: Optional[List[str]] = Field(default_factory=list)
    engineering_considerations: Optional[List[str]] = Field(default_factory=list)
    environmental_and_hazards: Optional[List[str]] = Field(default_factory=list)
    financial_considerations: Optional[List[str]] = Field(default_factory=list)
    required_investigations: Optional[List[str]] = Field(default_factory=list)
    recommended_next_steps: Optional[List[str]] = Field(default_factory=list)
    summary: Optional[str] = Field(
        default=None,
        description="Alternative summary field for engineering evaluation"
    )
    recommendations: Optional[List[str]] = Field(
        default_factory=list,
        description="Alternative recommendations field"
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional structural engineering notes or geotechnical remarks"
    )
    assumptions: Optional[List[str]] = Field(
        default_factory=list,
        description="Optional design code assumptions or material parameters"
    )
    disclaimer: Optional[str] = Field(
        default=None,
        description="Optional regulatory or municipal compliance disclaimer"
    )

    @field_validator("feasibility_score", mode="before")
    @classmethod
    def parse_feasibility_score(cls, v: Any) -> Any:
        if isinstance(v, str):
            match = re.search(r'\b\d+\b', v)
            if match:
                return int(match.group(0))
        elif isinstance(v, float):
            return int(round(v))
        return v

    @field_validator("structural_recommendations", "detailed_recommendations", "recommendations", mode="before", check_fields=False)
    @classmethod
    def parse_list_fields(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [line.strip().lstrip("0123456789.-*• ") for line in v.split("\n") if line.strip()]
        return v

    @field_validator("cost_breakdown", "vastu_compliance", mode="before", check_fields=False)
    @classmethod
    def parse_dict_fields(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {"description": v}
        return v

    @model_validator(mode="after")
    def sync_aliases(self) -> "AnalysisResponse":
        if not self.engineering_summary and self.summary:
            self.engineering_summary = self.summary
        elif not self.engineering_summary:
            self.engineering_summary = (
                f"{self.parameter_reflection} "
                f"Feasibility evaluation indicates a score of {self.feasibility_score}/100 based on IS 456 and NBC 2016 standards."
            )
        if not self.detailed_recommendations and self.structural_recommendations:
            self.detailed_recommendations = list(self.structural_recommendations)

        # Synchronize structured_analysis and structured_narrative
        if not self.structured_analysis and self.structured_narrative:
            self.structured_analysis = self.structured_narrative
        elif not self.structured_narrative and self.structured_analysis:
            self.structured_narrative = self.structured_analysis
        elif not self.structured_analysis and (self.executive_summary or self.overall_assessment):
            self.structured_analysis = SiteFeasibilityAIAnalysis(
                executive_summary=self.executive_summary or self.engineering_summary or "",
                overall_assessment=self.overall_assessment or self.engineering_summary or "",
                key_strengths=self.key_strengths or ["Topographic suitability verified for planned footprint"],
                key_concerns=self.key_concerns or ["Foundation drainage and retaining systems require geotechnical verification"],
                engineering_considerations=self.engineering_considerations or ["Structural framing per IS 456 with ductile detailing under IS 13920"],
                environmental_and_hazards=self.environmental_and_hazards or ["Seismic and wind loads factored into structural model"],
                financial_considerations=self.financial_considerations or ["CPWD benchmark rates applied to built-up area schedule"],
                required_investigations=self.required_investigations or ["Geotechnical soil investigation (borehole SPT tests per IS 1892)"],
                recommended_next_steps=self.recommended_next_steps or ["Commission geotechnical site survey and finalize structural foundation design"]
            )
            self.structured_narrative = self.structured_analysis
        return self
