"""
Schema discovery for a connected customer database.

Runs once at setup and on demand afterwards. The result is cached on the
connection row so the query planner never has to introspect a customer's
database mid-meeting.

Discovery reads the *catalog only* — table and column names, types, row
estimates. It never reads row data. That distinction matters at setup time:
a customer approving a connection should be able to see exactly what Donna
learned before any of their actual business data is touched.

Sensitive-looking columns are flagged here rather than hidden, so the customer
sees what was detected and can decide. Silently omitting them would make the
schema view a lie.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from apps.api.services.data_connection.connector import (
    ConnectionSpec,
    _connect,
    is_sensitive_column,
)

logger = logging.getLogger(__name__)

# System schemas are never business data.
_SKIP_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")

_TABLES_SQL = """
SELECT
    c.table_schema,
    c.table_name,
    c.column_name,
    c.data_type,
    c.is_nullable
FROM information_schema.columns c
JOIN information_schema.tables t
  ON  t.table_schema = c.table_schema
  AND t.table_name   = c.table_name
WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
  AND t.table_type IN ('BASE TABLE', 'VIEW')
ORDER BY c.table_schema, c.table_name, c.ordinal_position
"""

# Planner estimate, not a count(*) — counting every table on a large customer
# database at setup time would be exactly the kind of load this feature must
# not generate.
_ROWS_SQL = """
SELECT n.nspname AS schema_name, c.relname AS table_name,
       c.reltuples::bigint AS row_estimate
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'v', 'm', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
"""


async def introspect(
    spec: ConnectionSpec, allow_private: bool = False, max_tables: int = 300
) -> Dict[str, Any]:
    """Discover tables, columns and row estimates. Reads no row data."""
    conn = await _connect(spec, allow_private)
    try:
        col_rows = await conn.fetch(_TABLES_SQL)
        try:
            est_rows = await conn.fetch(_ROWS_SQL)
        except Exception:
            est_rows = []
    finally:
        await conn.close()

    estimates = {
        (r["schema_name"], r["table_name"]): int(r["row_estimate"]) for r in est_rows
    }

    tables: Dict[str, Dict[str, Any]] = {}
    for r in col_rows:
        schema, name = r["table_schema"], r["table_name"]
        if schema in _SKIP_SCHEMAS:
            continue
        key = f"{schema}.{name}"
        entry = tables.setdefault(
            key,
            {
                "schema": schema,
                "name": name,
                "qualified": key,
                "columns": [],
                "row_estimate": estimates.get((schema, name)),
                "sensitive_columns": [],
            },
        )
        col = {
            "name": r["column_name"],
            "type": r["data_type"],
            "nullable": r["is_nullable"] == "YES",
        }
        # Flagged, not hidden — the customer should see what was detected.
        if is_sensitive_column(r["column_name"]):
            col["sensitive"] = True
            entry["sensitive_columns"].append(r["column_name"])
        entry["columns"].append(col)

    ordered = sorted(
        tables.values(),
        key=lambda t: (-(t["row_estimate"] or 0), t["qualified"]),
    )[:max_tables]

    return {
        "tables": ordered,
        "table_count": len(tables),
        "truncated": len(tables) > max_tables,
    }


def schema_prompt(profile: Dict[str, Any], allowed: List[str]) -> str:
    """Render the APPROVED subset of the schema for an LLM planning prompt.

    Only approved tables appear. The model cannot reference a table it was
    never shown, which makes the allowlist a prompt-level control as well as
    an execution-level one — two independent layers rather than one.

    Sensitive columns are omitted entirely here: the planner should not be
    able to select them even by accident.
    """
    allowed_set = {a.strip().lower() for a in (allowed or [])}
    lines: List[str] = []
    for t in profile.get("tables", []):
        q = t["qualified"].lower()
        if (
            allowed_set
            and q not in allowed_set
            and t["name"].lower() not in allowed_set
        ):
            continue
        cols = [
            f"{c['name']} {c['type']}" for c in t["columns"] if not c.get("sensitive")
        ]
        if not cols:
            continue
        lines.append(f"{t['qualified']} ({', '.join(cols[:40])})")
    return "\n".join(lines)


def approved_tables(
    profile: Dict[str, Any], allowed: List[str]
) -> List[Dict[str, Any]]:
    """The table entries the customer has approved."""
    allowed_set = {a.strip().lower() for a in (allowed or [])}
    if not allowed_set:
        return []
    return [
        t
        for t in profile.get("tables", [])
        if t["qualified"].lower() in allowed_set or t["name"].lower() in allowed_set
    ]
