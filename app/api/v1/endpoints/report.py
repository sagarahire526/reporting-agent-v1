"""Report generation endpoint."""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException

from api.v1.schemas import ReportRequest, ReportResponse
from services.reporting_service import run_report
from services import db_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Reporting"])

# ── ANSI colors ──────────────────────────────────────────────────────────────
_CYAN = "\033[96m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


@router.post("/report", response_model=ReportResponse)
def generate_report(req: ReportRequest):
    """
    Generate Highcharts visualizations from a natural language query.

    Pipeline: schema discovery -> traversal agent -> data extraction -> chart generation
    All results are persisted to pwc_agent_utility_schema.reporting_agent_queries.
    """
    query_id = str(uuid.uuid4())
    start_time = time.perf_counter()

    print(f"\n{_BOLD}{'=' * 70}", flush=True)
    print(f"  REPORTING AGENT — New Report Request", flush=True)
    print(f"{'=' * 70}{_RESET}", flush=True)
    print(f"  {_DIM}Query ID    : {query_id}{_RESET}", flush=True)
    print(f"  {_DIM}User        : {req.username} ({req.user_id}){_RESET}", flush=True)
    print(f"  {_DIM}Query       : {req.query}{_RESET}", flush=True)
    print(f"  {_DIM}Project type: {req.project_type.value}{_RESET}", flush=True)
    print(f"  {_DIM}Max charts  : {req.max_charts}{_RESET}", flush=True)

    # Persist the incoming request
    db_service.create_query(
        query_id=query_id,
        user_id=req.user_id,
        username=req.username,
        original_query=req.query,
        project_type=req.project_type.value,
        max_charts=req.max_charts,
    )

    try:
        result = run_report(
            query=req.query,
            project_type=req.project_type.value,
            max_charts=req.max_charts,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Persist the result
        if result["status"] == "success":
            db_service.update_query_complete(
                query_id=query_id,
                charts=result.get("charts", []),
                rationale=result.get("rationale", ""),
                traversal_findings=result.get("traversal_findings", ""),
                traversal_steps=result.get("traversal_steps", 0),
                duration_ms=elapsed_ms,
                errors=result.get("errors"),
            )
            num_charts = len(result.get("charts", []))
            print(f"\n{_BOLD}{'=' * 70}", flush=True)
            print(f"  {_GREEN}SUCCESS — {num_charts} chart(s) generated in {elapsed_ms:.0f}ms{_RESET}", flush=True)
            print(f"{_BOLD}{'=' * 70}{_RESET}\n", flush=True)
        else:
            db_service.update_query_error(
                query_id=query_id,
                duration_ms=elapsed_ms,
                errors=result.get("errors"),
                traversal_findings=result.get("traversal_findings", ""),
                traversal_steps=result.get("traversal_steps", 0),
            )
            errs = result.get("errors", [])
            print(f"\n{_BOLD}{'=' * 70}", flush=True)
            print(f"  {_RED}FAILED after {elapsed_ms:.0f}ms — {errs}{_RESET}", flush=True)
            print(f"{_BOLD}{'=' * 70}{_RESET}\n", flush=True)

        return ReportResponse(
            query_id=query_id,
            status=result["status"],
            charts=result.get("charts", []),
            rationale=result.get("rationale", ""),
            query=req.query,
            traversal_steps=result.get("traversal_steps", 0),
            traversal_findings=result.get("traversal_findings", ""),
            errors=result.get("errors", []),
        )

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.error("Report generation failed: %s", e)
        print(f"\n  {_RED}EXCEPTION after {elapsed_ms:.0f}ms: {e}{_RESET}\n", flush=True)
        db_service.update_query_error(
            query_id=query_id,
            duration_ms=elapsed_ms,
            errors=[str(e)],
        )
        raise HTTPException(status_code=500, detail=str(e))
