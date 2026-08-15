"""
Agenda → SQL planning.

An LLM proposes SELECT statements against the *approved* subset of a
customer's schema; the guards decide whether any of them actually run. The
model is treated as an untrusted source of SQL throughout — it is a
convenience for phrasing a query, never an authority on what may execute.

Two independent layers, and the order matters:

  1. **Prompt scoping.** The model is shown only approved tables, with
     sensitive columns already stripped. It cannot reference what it never saw.
  2. **Execution guards.** Everything the model returns is re-validated
     (`guard.check_sql`, table allowlist, row cap) before it reaches the
     database. Layer 1 is not trusted to have worked.

Used on the cold path (pre-meeting research, where minutes are available) and
for explicit "Ask Donna" data questions. Never on the hot path — see
``indexer.py`` for how in-meeting nudges get their data without a live query.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from apps.api.core import json_parse, llm_provider
from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)

MAX_QUERIES_PER_PLAN = 4

_SYSTEM = """You write read-only PostgreSQL SELECT statements that help \
someone prepare for a meeting.

RULES — a violation makes the query unusable:
- SELECT only. Never INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/GRANT.
- One statement per query. No semicolons except a single trailing one.
- Only the tables and columns listed in the SCHEMA below. Nothing else exists.
- Always aggregate or filter. Prefer COUNT/SUM/AVG/GROUP BY over raw dumps.
- Always include an explicit LIMIT of 50 or fewer.
- No pg_* functions, no dblink, no file access.

Return JSON only:
{"queries":[{"question":"<what this answers, one line>","sql":"<SELECT ...>"}]}

Write at most %d queries. Prefer few, high-signal queries over many shallow \
ones. If the schema cannot answer anything useful about the agenda, return \
{"queries":[]} — an empty plan is a valid and useful answer.""" % (
    MAX_QUERIES_PER_PLAN,
)


class QueryPlanner:
    """Turns a meeting agenda into a small set of validated SELECT statements."""

    def __init__(self):
        self._client = None

    def _openai(self):
        if self._client is None:
            self._client = llm_provider.failover_client()
        return self._client

    @resilient_call("openai", max_retries=2, timeout_seconds=30)
    async def _propose(self, schema: str, topic: str, agenda: List[str]) -> str:
        agenda_text = "\n".join(f"- {a}" for a in agenda if a) or "(no agenda items)"
        resp = await self._openai().chat.completions.create(
            model=settings.model_fast,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"SCHEMA (the only tables that exist):\n{schema}\n\n"
                        f"MEETING: {topic}\n\nAGENDA:\n{agenda_text}\n\n"
                        "Which queries would give this meeting a factual base?"
                    ),
                },
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or "{}"

    async def plan(
        self,
        *,
        schema_prompt_text: str,
        topic: str,
        agenda: List[str],
        allowed_tables: List[str],
    ) -> List[Dict[str, str]]:
        """Return validated {question, sql} pairs. Invalid proposals are dropped.

        A rejected query is logged and discarded rather than repaired: an
        automatic "fix it" loop against someone else's production database is
        exactly the wrong place to be clever.
        """
        if not schema_prompt_text.strip():
            return []
        if not settings.openai_api_key:
            logger.info("[planner] no OPENAI_API_KEY — skipping query planning")
            return []

        try:
            raw = await self._propose(schema_prompt_text, topic, agenda)
            proposed = (json_parse.loads(raw, {}) or {}).get("queries", [])
        except Exception as e:
            logger.warning(f"[planner] proposal failed: {e}")
            return []

        from apps.api.services.data_connection.connector import (
            _tables_outside_allowlist,
        )
        from apps.api.services.data_connection.guard import check_sql

        approved: List[Dict[str, str]] = []
        for item in proposed[:MAX_QUERIES_PER_PLAN]:
            sql = (item or {}).get("sql") or ""
            question = (item or {}).get("question") or "Data lookup"

            verdict = check_sql(sql)
            if not verdict.allowed:
                logger.warning(
                    f"[planner] rejected a proposed query ({verdict.reason}): "
                    f"{sql[:120]}"
                )
                continue

            if allowed_tables:
                outside = _tables_outside_allowlist(verdict.normalized, allowed_tables)
                if outside:
                    # The model referenced a table it was never shown. Worth a
                    # warning: it means prompt scoping alone would not have
                    # been sufficient, which is why the second layer exists.
                    logger.warning(
                        "[planner] rejected a query referencing unapproved "
                        f"tables {sorted(outside)}: {sql[:120]}"
                    )
                    continue

            approved.append({"question": question, "sql": verdict.normalized})

        logger.info(
            f"[planner] {len(approved)}/{len(proposed)} proposed queries passed the guards"
        )
        return approved


query_planner = QueryPlanner()


def summarize_results(
    question: str, result: Any, max_rows: int = 12
) -> Optional[Dict[str, Any]]:
    """Compact a QueryResult into something an LLM prompt or a card can carry."""
    if result is None or not getattr(result, "rows", None):
        return None
    rows = result.rows[:max_rows]
    return {
        "question": question,
        "columns": result.columns,
        "rows": rows,
        "row_count": result.row_count,
        "truncated": result.truncated or result.row_count > max_rows,
    }
