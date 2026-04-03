"""
Streamlit UI for the Reporting Agent.

Renders Highcharts visualizations from natural language queries.
Run: streamlit run streamlit_app.py
"""
import sys
from pathlib import Path

# Ensure app/ is on sys.path for internal imports
_APP_DIR = str(Path(__file__).resolve().parent / "app")
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

import json
import streamlit as st # type: ignore[import-unresolved]
import streamlit.components.v1 as components  # type: ignore[import-unresolved]
import requests

# ── Configuration ────────────────────────────────────────────────────────────

API_BASE = "http://localhost:8000/api/v1"

PROJECT_TYPES = ["NTM", "AHLOB Modernization", "Both"]

# ── Highcharts Rendering ─────────────────────────────────────────────────────

# Load Highcharts JS from local file (bundled in static/)
_HIGHCHARTS_JS_PATH = Path(__file__).resolve().parent / "static" / "highcharts.js"
_HIGHCHARTS_JS = ""
if _HIGHCHARTS_JS_PATH.exists():
    _HIGHCHARTS_JS = _HIGHCHARTS_JS_PATH.read_text(encoding="utf-8")
    print(f"[STREAMLIT] Loaded Highcharts JS from {_HIGHCHARTS_JS_PATH} ({len(_HIGHCHARTS_JS)} bytes)", flush=True)
else:
    print(f"[STREAMLIT] WARNING: {_HIGHCHARTS_JS_PATH} not found — charts will not render!", flush=True)


def render_highchart(chart_config: dict, chart_index: int = 0, height: int = 450):
    """Render a single Highcharts chart using an HTML component with inlined JS."""
    container_id = f"chart-container-{chart_index}"
    config_json = json.dumps(chart_config, default=str)
    highcharts_js = _HIGHCHARTS_JS

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                margin: 0;
                padding: 0;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: transparent;
            }}
            #{container_id} {{
                width: 100%;
                height: {height - 20}px;
            }}
        </style>
        <script>{highcharts_js}</script>
    </head>
    <body>
        <div id="{container_id}"></div>
        <script>
            var config = {config_json};
            if (!config.chart) config.chart = {{}};
            config.chart.renderTo = '{container_id}';
            if (!config.credits) config.credits = {{ enabled: false }};
            Highcharts.chart(config);
        </script>
    </body>
    </html>
    """
    components.html(html, height=height, scrolling=False)


# ── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Reporting Agent",
    page_icon="📊",
    layout="wide",
)

st.title("Reporting Agent")
st.caption("Generate insightful Highcharts visualizations from natural language queries")

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Settings")

    user_id = st.text_input("User ID", value="demo_user", help="Your user identifier")
    username = st.text_input("Username", value="Demo User", help="Your display name")

    project_type = st.selectbox(
        "Project Type",
        options=PROJECT_TYPES,
        index=0,
        help="Filter data by project type",
    )

    max_charts = st.slider(
        "Max Charts",
        min_value=1,
        max_value=5,
        value=3,
        help="Maximum number of charts to generate",
    )

    st.divider()

    # Health check
    if st.button("Check Service Health"):
        try:
            resp = requests.get(f"{API_BASE}/health", timeout=10)
            health = resp.json()
            if health.get("status") == "ok":
                st.success("All services connected")
            else:
                st.warning("Some services degraded")
            for svc, info in health.get("services", {}).items():
                icon = "✅" if info.get("status") == "connected" else "❌"
                st.write(f"{icon} **{svc}**: {info.get('detail', info.get('status', 'unknown'))}")
        except Exception as e:
            st.error(f"Health check failed: {e}")

    st.divider()
    st.caption("Query History")
    if st.button("Load History"):
        try:
            from services.db_service import get_queries_by_user
            queries = get_queries_by_user(user_id, limit=10)
            if queries:
                for q in queries:
                    status_icon = "✅" if q.get("status") == "complete" else "❌"
                    label = f"{status_icon} {q['original_query'][:60]}..."
                    if st.button(label, key=q["query_id"]):
                        st.session_state["loaded_query"] = q
            else:
                st.info("No previous queries found.")
        except Exception as e:
            st.error(f"Could not load history: {e}")


# ── Main Content ─────────────────────────────────────────────────────────────

# Query input
query = st.text_area(
    "Enter your query",
    placeholder="e.g., What is the site completion rate by market for NTM projects?",
    height=80,
)

col1, col2 = st.columns([1, 5])
with col1:
    generate_btn = st.button("Generate Report", type="primary", use_container_width=True)

# ── Report Generation ────────────────────────────────────────────────────────

if generate_btn and query.strip():
    import urllib.parse

    progress_bar = st.progress(0, text="Starting report generation...")
    status_text = st.empty()

    try:
        params = urllib.parse.urlencode({
            "query": query.strip(),
            "project_type": project_type,
            "user_id": user_id,
            "username": username,
            "max_charts": max_charts,
        })
        sse_url = f"{API_BASE}/report/stream?{params}"

        resp = requests.get(sse_url, stream=True, timeout=300)

        if resp.status_code != 200:
            st.error(f"API error ({resp.status_code}): {resp.text}")
        else:
            result = None
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith(":"):  # heartbeat
                    continue
                if line.startswith("event: "):
                    current_event = line[7:]
                    continue
                if line.startswith("data: "):
                    data = json.loads(line[6:])

                    if current_event == "stream_started":
                        status_text.info(f"Report started (ID: {data.get('query_id', '?')[:8]}...)")

                    elif current_event == "step":
                        step = data.get("step", 0)
                        total = data.get("total", 3)
                        label = data.get("label", "Processing...")
                        progress_bar.progress(step / (total + 1), text=label)

                    elif current_event == "traversal_done":
                        steps = data.get("steps", 0)
                        ms = data.get("elapsed_ms", 0)
                        status_text.success(f"Traversal complete: {steps} tool call(s) in {ms/1000:.1f}s")

                    elif current_event == "complete":
                        progress_bar.progress(1.0, text="Report complete!")
                        status_text.empty()
                        result = data
                        st.session_state["last_result"] = result

                    elif current_event == "error":
                        progress_bar.empty()
                        status_text.error(f"Error: {data.get('message', 'Unknown error')}")

            if result is None and "last_result" not in st.session_state:
                progress_bar.empty()
                status_text.warning("Stream ended without a result.")

    except requests.exceptions.ConnectionError:
        progress_bar.empty()
        st.error(
            "Could not connect to the Reporting Agent API. "
            "Make sure the server is running: `uvicorn app.main:app --port 8001`"
        )
    except Exception as e:
        progress_bar.empty()
        st.error(f"Error: {e}")

elif generate_btn:
    st.warning("Please enter a query.")

# ── Display Results ──────────────────────────────────────────────────────────

# Check for loaded query from history
if "loaded_query" in st.session_state:
    q = st.session_state.pop("loaded_query")
    st.session_state["last_result"] = {
        "status": q.get("status", "complete"),
        "charts": q.get("charts", []),
        "rationale": q.get("rationale", ""),
        "query": q.get("original_query", ""),
        "traversal_steps": q.get("traversal_steps", 0),
        "traversal_findings": q.get("traversal_findings", ""),
        "errors": q.get("errors", []),
        "query_id": q.get("query_id", ""),
    }

if "last_result" in st.session_state:
    result = st.session_state["last_result"]

    if result["status"] == "success":
        charts = result.get("charts", [])
        rationale = result.get("rationale", "")

        if charts:
            st.success(f"Generated {len(charts)} chart(s)")

            # Rationale
            if rationale:
                st.info(f"**Insight:** {rationale}")

            # Render each chart with description
            for i, chart_config in enumerate(charts):
                title = "Chart"
                if isinstance(chart_config.get("title"), dict):
                    title = chart_config["title"].get("text", f"Chart {i+1}")
                elif isinstance(chart_config.get("title"), str):
                    title = chart_config["title"]

                st.subheader(f"{i+1}. {title}")

                # Chart description
                description = chart_config.get("description", "")
                if description:
                    st.caption(description)

                render_highchart(chart_config, chart_index=i)

            # Raw JSON expandable
            with st.expander("View raw Highcharts JSON"):
                st.json(charts)

        else:
            st.warning("Report generated but no charts were produced.")

    else:
        st.error("Report generation failed.")
        errors = result.get("errors", [])
        for err in errors:
            st.error(err)

    # Traversal details
    with st.expander("Traversal Agent Details"):
        st.write(f"**Tool calls:** {result.get('traversal_steps', 0)}")
        findings = result.get("traversal_findings", "")
        if findings:
            st.text_area("Findings", value=findings, height=200, disabled=True)
        else:
            st.info("No traversal findings available.")
