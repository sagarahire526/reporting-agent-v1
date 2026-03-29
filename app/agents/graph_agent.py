"""
Graph Agent — LLM-powered Highcharts chart generation.

Analyzes tabular data from the traversal agent and produces
insightful Highcharts configuration objects.
"""
from __future__ import annotations

import json
import time
import logging
from typing import Any

from services.llm_provider import LLMProvider
from prompts.graph_agent_prompt import GRAPH_AGENT_SYSTEM, GRAPH_AGENT_USER
from utils.data_extractor import format_datasets_for_llm

logger = logging.getLogger(__name__)

MAX_RETRIES = 2

# ── ANSI colors ──────────────────────────────────────────────────────────────
_CYAN = "\033[96m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _print_divider(char: str = "-", width: int = 70):
    print(f"{_DIM}{char * width}{_RESET}", flush=True)


def _strip_markdown_fences(content: str) -> str:
    """Remove markdown code fences if the LLM wraps its JSON output."""
    content = content.strip()
    if content.startswith("```"):
        first_newline = content.index("\n")
        content = content[first_newline + 1:]
        if content.endswith("```"):
            content = content[:-3].strip()
    return content


def _validate_chart_structure(parsed: dict) -> list[str]:
    """Validate the parsed JSON has the required structure. Returns list of issues."""
    issues = []

    if not isinstance(parsed, dict):
        issues.append("Response is not a JSON object")
        return issues

    if "charts" not in parsed:
        issues.append("Missing required 'charts' key")
        return issues

    if not isinstance(parsed["charts"], list):
        issues.append("'charts' must be an array")
        return issues

    for i, chart in enumerate(parsed["charts"]):
        if not isinstance(chart, dict):
            issues.append(f"Chart {i+1} is not a JSON object")
            continue

        chart_type = None
        if "chart" in chart and isinstance(chart["chart"], dict):
            chart_type = chart["chart"].get("type")
        elif "type" in chart:
            chart_type = chart["type"]

        if not chart_type:
            issues.append(f"Chart {i+1} missing chart type (need chart.type or type)")

        if "title" not in chart:
            issues.append(f"Chart {i+1} missing title")

        if "series" not in chart or not isinstance(chart.get("series"), list):
            issues.append(f"Chart {i+1} missing series array")
        elif chart["series"]:
            for j, s in enumerate(chart["series"]):
                if "data" not in s:
                    issues.append(f"Chart {i+1}, series {j+1} missing data")

    return issues


def generate_charts(
    user_query: str,
    datasets: list[dict],
    traversal_findings: str,
    max_charts: int = 3,
) -> dict[str, Any]:
    """
    Generate Highcharts configurations from traversal data.

    Uses GPT-4o to analyze datasets and produce insightful chart configs.
    Includes JSON validation with retry on failure.

    Returns:
        {"charts": [...], "rationale": "..."}

    Raises:
        ValueError if all retries fail to produce valid JSON.
    """
    print(f"\n{_BOLD}{'=' * 70}", flush=True)
    print(f"  CHART AGENT — Generating Highcharts Visualizations", flush=True)
    print(f"{'=' * 70}{_RESET}\n", flush=True)

    print(f"  {_DIM}Datasets: {len(datasets)}, max charts: {max_charts}{_RESET}", flush=True)
    print(f"  {_DIM}Findings: {len(traversal_findings)} chars{_RESET}\n", flush=True)

    provider = LLMProvider(model="gpt-4o", temperature=0.1)

    formatted_data = format_datasets_for_llm(datasets, max_rows_per_dataset=30)
    print(f"  {_DIM}Formatted data for LLM: {len(formatted_data)} chars{_RESET}", flush=True)

    system_prompt = GRAPH_AGENT_SYSTEM.format(max_charts=max_charts)
    user_message = GRAPH_AGENT_USER.format(
        user_query=user_query,
        traversal_findings=traversal_findings,
        formatted_datasets=formatted_data,
        max_charts=max_charts,
    )

    messages = [
        ("system", system_prompt),
        ("human", user_message),
    ]

    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        _print_divider()
        print(f"{_BOLD}{_CYAN}  LLM Call {attempt + 1}/{MAX_RETRIES + 1}{_RESET}", flush=True)
        t0 = time.perf_counter()
        try:
            response = provider.invoke(messages)
            llm_ms = (time.perf_counter() - t0) * 1000
            content = response.content.strip()
            print(f"     {_GREEN}OK Response:{_RESET} {len(content)} chars in {llm_ms:.0f}ms", flush=True)

            content = _strip_markdown_fences(content)

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as e:
                last_error = f"Invalid JSON: {e}"
                print(f"     {_RED}X JSON parse failed:{_RESET} {e}", flush=True)
                print(f"     {_DIM}Preview: {content[:150]}...{_RESET}", flush=True)
                if attempt < MAX_RETRIES:
                    messages.append(("assistant", content))
                    messages.append(("human",
                        f"Your response was not valid JSON. Error: {e}. "
                        f"Please output ONLY a valid JSON object with 'charts' and 'rationale' keys. "
                        f"No markdown, no code fences, no text outside the JSON."
                    ))
                    continue
                raise ValueError(f"Failed to get valid JSON after {MAX_RETRIES + 1} attempts: {e}")

            issues = _validate_chart_structure(parsed)
            if issues:
                last_error = f"Structural issues: {'; '.join(issues)}"
                print(f"     {_RED}X Validation failed:{_RESET} {'; '.join(issues)}", flush=True)
                if attempt < MAX_RETRIES:
                    messages.append(("assistant", content))
                    messages.append(("human",
                        f"Your JSON is valid but has structural issues: {'; '.join(issues)}. "
                        f"Fix these issues and output the corrected JSON. "
                        f"Every chart needs: chart.type, title, and series with data."
                    ))
                    continue
                if "charts" in parsed:
                    logger.warning("Chart validation issues on final attempt: %s", issues)
                    break
                raise ValueError(f"Invalid chart structure after {MAX_RETRIES + 1} attempts: {issues}")

            if "rationale" not in parsed:
                parsed["rationale"] = "Charts generated based on the available data."

            # Print chart summary
            print(flush=True)
            charts = parsed.get("charts", [])
            for i, c in enumerate(charts, 1):
                ctype = c.get("chart", {}).get("type", c.get("type", "?"))
                ctitle = c.get("title", {}).get("text", "?") if isinstance(c.get("title"), dict) else str(c.get("title", "?"))
                num_series = len(c.get("series", []))
                print(f"  {_CYAN}  Chart {i}:{_RESET} {ctype} — \"{ctitle}\" ({num_series} series)", flush=True)

            rationale = parsed.get("rationale", "")
            if rationale:
                print(f"\n  {_YELLOW}Rationale:{_RESET} {rationale[:200]}", flush=True)

            _print_divider("=")
            print(f"  {_BOLD}Chart generation complete: {len(charts)} chart(s){_RESET}", flush=True)
            _print_divider("=")
            print(flush=True)

            return parsed

        except ValueError:
            raise
        except Exception as e:
            llm_ms = (time.perf_counter() - t0) * 1000
            last_error = str(e)
            logger.error("Chart generation attempt %d failed: %s", attempt + 1, e)
            print(f"     {_RED}X Exception after {llm_ms:.0f}ms:{_RESET} {e}", flush=True)
            if attempt >= MAX_RETRIES:
                raise ValueError(f"Chart generation failed after {MAX_RETRIES + 1} attempts: {last_error}")

    # Fallback — should not reach here normally
    return parsed
