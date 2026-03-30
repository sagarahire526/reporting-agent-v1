"""
Reporting Service — Orchestrates the full reporting pipeline.

Pipeline:
    1. Schema Discovery → neo4j_tool.get_schema()
    2. Traversal Agent  → traversal_node(state) → raw data + findings
    3. Chart Generation → generate_charts(LLM gets raw tool outputs directly)
"""
from __future__ import annotations

import time
import logging
from typing import Any

from tools.neo4j_tool import neo4j_tool
from agents.traversal import traversal_node
from agents.graph_agent import generate_charts

logger = logging.getLogger(__name__)

# ── ANSI colors ──────────────────────────────────────────────────────────────
_CYAN = "\033[96m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def run_report(
    query: str,
    project_type: str,
    max_charts: int = 3,
) -> dict[str, Any]:
    """
    Execute the full reporting pipeline.

    Args:
        query: Natural language user query
        project_type: "NTM" | "AHLOB Modernization" | "Both"
        max_charts: Maximum number of charts to generate (default 3)

    Returns:
        {
            "status": "success" | "error",
            "charts": [...],
            "rationale": "...",
            "traversal_steps": int,
            "traversal_findings": str,
            "errors": [...]
        }
    """
    errors = []
    pipeline_start = time.perf_counter()

    # ── Step 1: Schema Discovery ──────────────────────────────────────────
    print(f"\n  {_BOLD}{_CYAN}Step 1/3:{_RESET} Discovering KG schema...", flush=True)
    t0 = time.perf_counter()
    try:
        kg_schema = neo4j_tool.get_schema()
    except Exception as e:
        logger.error("Schema discovery failed: %s", e)
        print(f"  {_RED}X Schema discovery failed: {e}{_RESET}\n", flush=True)
        return {
            "status": "error",
            "charts": [],
            "rationale": "",
            "traversal_steps": 0,
            "traversal_findings": "",
            "errors": [f"Schema discovery failed: {e}"],
        }
    schema_ms = (time.perf_counter() - t0) * 1000
    schema_lines = kg_schema.count("\n") + 1
    print(f"  {_GREEN}OK Schema:{_RESET} {schema_lines} lines in {schema_ms:.0f}ms", flush=True)

    # ── Step 2: Traversal Agent ───────────────────────────────────────────
    print(f"\n  {_BOLD}{_CYAN}Step 2/3:{_RESET} Running traversal agent...", flush=True)
    t0 = time.perf_counter()
    state = {
        "user_query": query,
        "project_type": project_type,
        "kg_schema": kg_schema,
        "max_traversal_steps": 15,
    }

    traversal_result = traversal_node(state)
    traversal_ms = (time.perf_counter() - t0) * 1000

    traversal_findings = traversal_result.get("traversal_findings", "")
    traversal_steps = traversal_result.get("traversal_steps_taken", 0)
    tool_calls = traversal_result.get("traversal_tool_calls", [])

    if traversal_result.get("errors"):
        errors.extend(traversal_result["errors"])

    print(f"  {_GREEN}OK Traversal:{_RESET} {traversal_steps} tool call(s) in {traversal_ms:.0f}ms", flush=True)

    if traversal_findings.startswith("Traversal failed"):
        print(f"  {_RED}X Traversal failed — aborting pipeline{_RESET}\n", flush=True)
        return {
            "status": "error",
            "charts": [],
            "rationale": "",
            "traversal_steps": traversal_steps,
            "traversal_findings": traversal_findings,
            "errors": errors or [traversal_findings],
        }

    # ── Step 3: Chart Generation (LLM gets raw tool outputs) ─────────────
    print(f"\n  {_BOLD}{_CYAN}Step 3/3:{_RESET} Generating Highcharts (max {max_charts})...", flush=True)
    t0 = time.perf_counter()
    try:
        chart_result = generate_charts(
            user_query=query,
            tool_calls=tool_calls,
            traversal_findings=traversal_findings,
            max_charts=max_charts,
        )
        chart_ms = (time.perf_counter() - t0) * 1000
        charts = chart_result.get("charts", [])

        total_ms = (time.perf_counter() - pipeline_start) * 1000
        print(f"  {_GREEN}OK Charts:{_RESET} {len(charts)} chart(s) in {chart_ms:.0f}ms", flush=True)
        print(f"\n  {_BOLD}Pipeline complete — {total_ms:.0f}ms total{_RESET}\n", flush=True)

        return {
            "status": "success",
            "charts": charts,
            "rationale": chart_result.get("rationale", ""),
            "traversal_steps": traversal_steps,
            "traversal_findings": traversal_findings,
            "errors": errors,
        }

    except ValueError as e:
        chart_ms = (time.perf_counter() - t0) * 1000
        logger.error("Chart generation failed: %s", e)
        print(f"  {_RED}X Chart generation failed after {chart_ms:.0f}ms: {e}{_RESET}\n", flush=True)
        errors.append(f"Chart generation failed: {e}")
        return {
            "status": "error",
            "charts": [],
            "rationale": "",
            "traversal_steps": traversal_steps,
            "traversal_findings": traversal_findings,
            "errors": errors,
        }

    except Exception as e:
        chart_ms = (time.perf_counter() - t0) * 1000
        logger.error("Unexpected error in chart generation: %s", e)
        print(f"  {_RED}X Unexpected error after {chart_ms:.0f}ms: {e}{_RESET}\n", flush=True)
        errors.append(f"Unexpected error: {e}")
        return {
            "status": "error",
            "charts": [],
            "rationale": "",
            "traversal_steps": traversal_steps,
            "traversal_findings": traversal_findings,
            "errors": errors,
        }
