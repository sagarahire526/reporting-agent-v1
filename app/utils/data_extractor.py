"""
Data Extractor — Extract tabular data from traversal agent tool call records.

Parses run_sql_python outputs to produce structured datasets
that the Graph Agent can use for chart generation.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── ANSI colors ──────────────────────────────────────────────────────────────
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def extract_chart_data(tool_calls: list[dict]) -> list[dict]:
    """
    Extract structured tabular data from traversal tool_call records.

    Scans all successful run_sql_python tool calls and extracts their
    result payloads as datasets for chart generation.

    Returns:
        List of dicts, each with:
        - "summary": dict (pre-computed aggregates if available)
        - "detail_rows": list[dict] (actual data rows)
        - "total_rows": int
        - "source_query": str (the code that produced this data)
    """
    datasets = []

    for idx, tc in enumerate(tool_calls, 1):
        tool_name = tc.get("tool_name", "?")
        status = tc.get("status", "?")

        if tool_name != "run_sql_python":
            continue
        if status != "success":
            print(f"    {_YELLOW}Skipped call {idx} ({tool_name}): status={status}{_RESET}", flush=True)
            continue

        raw_output = tc.get("tool_output", "")

        try:
            if isinstance(raw_output, str):
                parsed = json.loads(raw_output)
            elif isinstance(raw_output, dict):
                parsed = raw_output
            else:
                continue
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse tool_output as JSON, skipping")
            continue

        if parsed.get("status") == "error":
            continue

        result = parsed.get("result")
        if not result:
            continue

        source_query = ""
        tool_input = tc.get("tool_input", {})
        if isinstance(tool_input, dict):
            source_query = tool_input.get("code", "")
        elif isinstance(tool_input, str):
            source_query = tool_input

        # Case 1: result is a dict with summary/detail_rows/total_rows
        if isinstance(result, dict):
            summary = result.get("summary", {})
            detail_rows = result.get("detail_rows", [])
            total_rows = result.get("total_rows", 0)

            if not detail_rows and not summary:
                datasets.append({
                    "summary": result,
                    "detail_rows": [],
                    "total_rows": 0,
                    "source_query": source_query,
                })
                continue

            if detail_rows or summary:
                actual_rows = len(detail_rows) if isinstance(detail_rows, list) else 0
                datasets.append({
                    "summary": summary if isinstance(summary, dict) else {},
                    "detail_rows": detail_rows if isinstance(detail_rows, list) else [],
                    "total_rows": total_rows if isinstance(total_rows, int) else actual_rows,
                    "source_query": source_query,
                })

        # Case 2: result is a list of dicts (raw query rows)
        elif isinstance(result, list) and result and isinstance(result[0], dict):
            datasets.append({
                "summary": {},
                "detail_rows": result[:50],
                "total_rows": len(result),
                "source_query": source_query,
            })

    return datasets


def format_datasets_for_llm(datasets: list[dict], max_rows_per_dataset: int = 30) -> str:
    """
    Format extracted datasets into a readable string for the Graph Agent LLM.

    Includes column names, data types, row counts, and sample data
    so the LLM can make informed chart decisions.
    """
    if not datasets:
        return "No datasets available."

    sections = []

    for i, ds in enumerate(datasets, 1):
        lines = [f"## Dataset {i}"]

        summary = ds.get("summary", {})
        detail_rows = ds.get("detail_rows", [])
        total_rows = ds.get("total_rows", 0)

        # Summary section
        if summary:
            lines.append(f"\n### Summary (pre-computed aggregates)")
            lines.append(json.dumps(summary, indent=2, default=str))

        # Detail rows section
        if detail_rows:
            columns = list(detail_rows[0].keys())
            lines.append(f"\n### Detail Rows ({total_rows} total, showing first {min(len(detail_rows), max_rows_per_dataset)})")
            lines.append(f"Columns: {', '.join(columns)}")

            type_info = []
            for col in columns:
                val = detail_rows[0].get(col)
                if isinstance(val, (int, float)):
                    type_info.append(f"{col}: numeric")
                elif isinstance(val, str):
                    type_info.append(f"{col}: text")
                else:
                    type_info.append(f"{col}: {type(val).__name__}")
            lines.append(f"Types: {', '.join(type_info)}")

            sample = detail_rows[:max_rows_per_dataset]
            lines.append(f"\nData:")
            lines.append(json.dumps(sample, indent=2, default=str))

        elif not summary:
            lines.append("No data rows or summary available.")

        sections.append("\n".join(lines))

    return "\n\n---\n\n".join(sections)
