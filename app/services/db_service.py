"""
DB Service — handles all persistence to pwc_agent_utility_schema.

Writes to one table:
  • reporting_agent_queries — one row per report generation request

Design rules:
  - Every function opens and closes its own connection.
  - DB errors are logged but NEVER raised — DB failures must not block
    the agent from returning a response to the user.
"""
from __future__ import annotations

import json
import logging
import uuid

import psycopg2

import config

logger = logging.getLogger(__name__)

_SCHEMA = "pwc_agent_utility_schema"


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _conn():
    """Open a new read-write psycopg2 connection."""
    return psycopg2.connect(
        host=config.PG_HOST,
        port=config.PG_PORT,
        database=config.PG_DATABASE,
        user=config.PG_USER,
        password=config.PG_PASSWORD,
        connect_timeout=5,
    )


def ensure_tables() -> None:
    """
    Create all required tables in pwc_agent_utility_schema if they do not exist.
    Called once at application startup.
    """
    ddl = f"""
        CREATE TABLE IF NOT EXISTS {_SCHEMA}.reporting_agent_queries (
            query_id            VARCHAR(100)    PRIMARY KEY,
            user_id             VARCHAR(100)    NOT NULL,
            username            VARCHAR(255)    NOT NULL,
            original_query      TEXT            NOT NULL,
            project_type        VARCHAR(50)     NOT NULL,
            max_charts          SMALLINT        NOT NULL DEFAULT 3,
            status              VARCHAR(20)     NOT NULL DEFAULT 'running',
            charts              JSONB,
            rationale           TEXT,
            traversal_findings  TEXT,
            traversal_steps     SMALLINT        DEFAULT 0,
            errors              JSONB,
            started_at          TIMESTAMP       NOT NULL DEFAULT NOW(),
            completed_at        TIMESTAMP,
            duration_ms         NUMERIC(12, 2)
        );
    """
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
        logger.info("reporting_agent_queries table verified / created.")
    except Exception as exc:
        logger.error("ensure_tables failed: %s", exc)


def _exec(sql: str, params: tuple) -> None:
    """Execute a single DML statement. Logs and swallows all DB errors."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
    except Exception as exc:
        logger.error("DB write failed — %.80s | error=%s", sql, exc)


def _fetch_rows(sql: str, params: tuple) -> list[dict]:
    """Fetch all rows as a list of dicts. Returns [] on error or no results."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        logger.error("DB read failed — %.80s | error=%s", sql, exc)
        return []


def _fetch_row(sql: str, params: tuple) -> dict | None:
    """Fetch a single row as a dict. Returns None on error or no result."""
    rows = _fetch_rows(sql, params)
    return rows[0] if rows else None


# ─────────────────────────────────────────────
# Write operations
# ─────────────────────────────────────────────

def create_query(
    query_id: str,
    user_id: str,
    username: str,
    original_query: str,
    project_type: str,
    max_charts: int = 3,
) -> None:
    """Insert a new query row with status=running at the moment of receipt."""
    _exec(
        f"""
        INSERT INTO {_SCHEMA}.reporting_agent_queries
            (query_id, user_id, username, original_query, project_type,
             max_charts, started_at, status)
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), 'running')
        """,
        (query_id, user_id, username, original_query, project_type, max_charts),
    )


def update_query_complete(
    query_id: str,
    charts: list[dict],
    rationale: str,
    traversal_findings: str,
    traversal_steps: int,
    duration_ms: float,
    errors: list[str] | None = None,
) -> None:
    """Finalize a completed query with chart results."""
    _exec(
        f"""
        UPDATE {_SCHEMA}.reporting_agent_queries SET
            status              = 'complete',
            charts              = %s,
            rationale           = %s,
            traversal_findings  = %s,
            traversal_steps     = %s,
            errors              = %s,
            completed_at        = NOW(),
            duration_ms         = %s
        WHERE query_id = %s
        """,
        (
            json.dumps(charts, default=str),
            rationale,
            traversal_findings,
            traversal_steps,
            json.dumps(errors) if errors else None,
            duration_ms,
            query_id,
        ),
    )


def update_query_error(
    query_id: str,
    duration_ms: float,
    errors: list[str] | None = None,
    traversal_findings: str = "",
    traversal_steps: int = 0,
) -> None:
    """Mark query as errored with the elapsed duration."""
    _exec(
        f"""
        UPDATE {_SCHEMA}.reporting_agent_queries SET
            status              = 'error',
            traversal_findings  = %s,
            traversal_steps     = %s,
            errors              = %s,
            completed_at        = NOW(),
            duration_ms         = %s
        WHERE query_id = %s
        """,
        (
            traversal_findings,
            traversal_steps,
            json.dumps(errors) if errors else None,
            duration_ms,
            query_id,
        ),
    )


# ─────────────────────────────────────────────
# Read operations
# ─────────────────────────────────────────────

def get_queries_by_user(user_id: str, limit: int = 50) -> list[dict]:
    """Return recent queries for a user, most recent first."""
    return _fetch_rows(
        f"""
        SELECT
            query_id, user_id, username, original_query, project_type,
            max_charts, status, charts, rationale, traversal_findings,
            traversal_steps, errors, started_at, completed_at, duration_ms
        FROM {_SCHEMA}.reporting_agent_queries
        WHERE user_id = %s
        ORDER BY started_at DESC
        LIMIT %s
        """,
        (user_id, limit),
    )


def get_query(query_id: str) -> dict | None:
    """Return a single query row by its ID."""
    return _fetch_row(
        f"""
        SELECT
            query_id, user_id, username, original_query, project_type,
            max_charts, status, charts, rationale, traversal_findings,
            traversal_steps, errors, started_at, completed_at, duration_ms
        FROM {_SCHEMA}.reporting_agent_queries
        WHERE query_id = %s
        """,
        (query_id,),
    )


def get_all_queries(limit: int = 100) -> list[dict]:
    """Return recent queries across all users."""
    return _fetch_rows(
        f"""
        SELECT
            query_id, user_id, username, original_query, project_type,
            max_charts, status, charts, rationale, traversal_findings,
            traversal_steps, errors, started_at, completed_at, duration_ms
        FROM {_SCHEMA}.reporting_agent_queries
        ORDER BY started_at DESC
        LIMIT %s
        """,
        (limit,),
    )
