"""Pydantic request/response models for the Reporting Agent API."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProjectType(str, Enum):
    NTM = "NTM"
    AHLOB_MODERNIZATION = "AHLOB Modernization"
    BOTH = "Both"


class ReportRequest(BaseModel):
    """Request body for report generation."""
    query: str = Field(..., description="Natural language query about telecom deployment data")
    project_type: ProjectType = Field(..., description="Project type filter")
    user_id: str = Field(..., description="User identifier")
    username: str = Field(..., description="Display name of the user")
    max_charts: int = Field(default=3, ge=1, le=5, description="Maximum number of charts to generate")


class ReportResponse(BaseModel):
    """Response body containing Highcharts configurations."""
    query_id: str = Field(default="", description="Unique identifier for this report query")
    status: str = Field(..., description="'success' or 'error'")
    charts: list[dict[str, Any]] = Field(default_factory=list, description="Highcharts config objects")
    rationale: str = Field(default="", description="Explanation of chart choices and insights")
    query: str = Field(default="", description="Original user query")
    traversal_steps: int = Field(default=0, description="Number of tool calls the traversal agent made")
    traversal_findings: str = Field(default="", description="Raw findings text from traversal agent")
    errors: list[str] = Field(default_factory=list, description="Any errors encountered")
