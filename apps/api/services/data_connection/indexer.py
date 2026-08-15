"""
Snapshot approved customer tables into the vector store.

This is what makes in-meeting insights possible *without* querying a
customer's production database on the hot path. The context agent has a 10s
budget and runs on every utterance; live text-to-SQL there would blow the
latency budget, add LLM cost per utterance, and — worst — put generated SQL
against someone's production database on the critical path of a live meeting.

So: a background job pulls approved tables, renders each row as a compact
natural-language fact, and indexes it into the same Qdrant collections as
documents and meeting memories, carrying the same ``owner_id`` payload. The
context agent then works completely unchanged.

Consequences, stated plainly:
  * Data is as fresh as the last sync, not live. For automatic nudges that is
    the right trade; explicit questions take the live path (``service.py``).
  * Only approved tables, only non-sensitive columns, and a bounded number of
    rows per table ever leave the customer's database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from apps.api.services.data_connection import introspect
from apps.api.services.data_connection.guard import safe_identifier

logger = logging.getLogger(__name__)

# Per-table ceiling. A snapshot is a *sample for context*, not a replica —
# copying a customer's entire database into a vector store would be a
# different product with a different consent conversation.
ROWS_PER_TABLE = 200


class IndexingFailedError(RuntimeError):
    """Rows were read but could not be embedded/stored. Carries a usable reason."""


def _row_to_sentence(table: str, columns: List[str], row: Dict[str, Any]) -> str:
    """Render one row as a retrievable fact.

    Embeddings work on prose, not tuples: "Customer Acme Systems has status
    active and region EU" retrieves far better than "Acme Systems|active|EU".
    The table name is included so retrieval can distinguish a customers row
    from an orders row that mentions the same name.
    """
    parts = []
    for c in columns:
        v = row.get(c)
        if v is None or v == "":
            continue
        parts.append(f"{c.replace('_', ' ')}: {v}")
    if not parts:
        return ""
    return f"[{table}] " + "; ".join(parts)


async def snapshot_connection(
    conn,
    session,
    *,
    allow_private: bool = False,
    rows_per_table: int = ROWS_PER_TABLE,
) -> Dict[str, Any]:
    """Pull approved tables and index them. Returns a per-table report."""
    from apps.api.services.data_connection.service import run_audited

    allowed = list(conn.allowed_tables or [])
    if not allowed:
        return {"indexed_rows": 0, "tables": [], "note": "no tables approved"}

    profile = conn.schema_profile or {}
    tables = introspect.approved_tables(profile, allowed)
    report: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []

    for t in tables:
        schema, name = t["schema"], t["name"]
        if not (safe_identifier(schema) and safe_identifier(name)):
            logger.warning(f"[indexer] skipping unsafe identifier: {schema}.{name}")
            continue

        cols = [
            c["name"]
            for c in t["columns"]
            if not c.get("sensitive") and safe_identifier(c["name"])
        ][:25]
        if not cols:
            report.append(
                {"table": t["qualified"], "rows": 0, "reason": "no safe columns"}
            )
            continue

        col_list = ", ".join(f'"{c}"' for c in cols)
        sql = f'SELECT {col_list} FROM "{schema}"."{name}"'

        result = await run_audited(session, conn, sql, purpose="snapshot")
        if result is None:
            report.append(
                {"table": t["qualified"], "rows": 0, "reason": "query refused"}
            )
            continue

        n = 0
        for row in result.rows[:rows_per_table]:
            text = _row_to_sentence(t["qualified"], result.columns, row)
            if not text:
                continue
            records.append(
                {
                    "text": text,
                    "metadata": {
                        "source_type": "customer_database",
                        "connection_name": conn.name,
                        "table": t["qualified"],
                    },
                }
            )
            n += 1
        report.append({"table": t["qualified"], "rows": n})

    rows_read = len(records)
    try:
        indexed = await _index_records(records, owner_id=conn.owner_id, conn=conn)
        index_error = None
    except IndexingFailedError as e:
        indexed = 0
        index_error = str(e)

    # Only stamp a successful sync. Recording last_indexed_at after a failure
    # would claim a freshness the snapshot does not have.
    if index_error is None:
        conn.last_indexed_at = datetime.now(timezone.utc)
        conn.indexed_row_count = indexed
        await session.commit()

    logger.info(
        f"[indexer] connection {conn.id}: read {rows_read} row(s), indexed "
        f"{indexed} across {len(report)} table(s)"
        + (f" — INDEXING FAILED: {index_error}" if index_error else "")
    )
    return {
        "indexed_rows": indexed,
        "rows_read": rows_read,
        "tables": report,
        "error": index_error,
    }


async def _index_records(records: List[Dict[str, Any]], *, owner_id, conn) -> Any:
    """Embed and store, reusing the meeting-memory indexing path.

    Deliberately NOT a new storage path. ``store_memory_records`` already
    writes a single-level vector to every collection with an ``owner_id``
    payload and idempotent point ids — which is exactly the contract customer
    data needs. Reusing it means the context agent's existing owner-scoped
    retrieval picks this up with no changes, and there is one indexing
    behaviour to reason about rather than two.

    The synthetic "meeting id" is ``db:<connection-id>``, so a re-sync
    overwrites the previous snapshot instead of accumulating duplicates.
    """
    if not records:
        return 0
    try:
        from apps.api.services.document.contextual_processor import (
            ContextualEmbeddingGenerator,
        )
        from apps.api.services.document.vector_store import ModernVectorStore

        store = ModernVectorStore()
        await store.initialize()

        embedder = ContextualEmbeddingGenerator()
        vectors = await embedder._embed_batch([r["text"] for r in records])

        payload_records = []
        for rec, vector in zip(records, vectors):
            if not vector:
                continue
            payload_records.append(
                {
                    "content": rec["text"],
                    "embedding": vector,
                    "metadata": {
                        # memory_kind participates in the idempotent point id,
                        # so per-table keys keep tables independent on re-sync.
                        "memory_kind": f"db:{rec['metadata']['table']}",
                        **rec["metadata"],
                    },
                }
            )

        return await store.store_memory_records(
            meeting_id=f"db:{conn.id}",
            records=payload_records,
            owner_id=str(owner_id) if owner_id else None,
        )
    except Exception as e:
        # Return the REASON, not just zero. Reporting "synced, 0 facts" for a
        # failed embedding call is the silent-failure pattern this codebase has
        # been bitten by before: the read succeeded, the indexing did not, and
        # the UI cheerfully said "Last synced".
        msg = str(e)
        if "insufficient_quota" in msg or "credit_balance" in msg:
            reason = (
                "Embedding failed — OpenAI credits exhausted. The rows WERE read "
                "from your database, but they could not be indexed for in-meeting "
                "use. Add credits and re-sync."
            )
        elif "429" in msg or "rate" in msg.lower():
            reason = "Embedding failed — provider rate limit. Re-sync shortly."
        else:
            reason = f"Embedding failed — {msg[:180]}"
        logger.error(f"[indexer] indexing failed: {e}")
        raise IndexingFailedError(reason) from e
