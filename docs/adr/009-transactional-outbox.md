# ADR-009: Transactional outbox for Postgres → Neo4j

**Status:** Accepted · **Date:** 2026-08

## Context
The summary pipeline wrote to Postgres and then called
`sync_meeting_to_neo4j()`. On failure the exception was caught and logged as
`"KG sync skipped"`. Postgres and the graph then disagreed **permanently**:
nothing detected the divergence and nothing replayed it, so the memory agent
would silently stop recalling decisions that demonstrably existed.

## Decision
Adopt the transactional outbox pattern. The **intent** to write to Neo4j is
committed to Postgres (`doc_intel.kg_outbox`) in the same transaction as the
data it describes. A drainer applies pending rows with retries and idempotent
Cypher (`MERGE`, not `CREATE`), so replay converges.

- Enqueue joins the caller's transaction and never commits on its own.
- The payload is self-contained, so replay does not re-read mutable state and
  therefore cannot apply a *different* write than the one intended.
- Rows are claimed `FOR UPDATE SKIP LOCKED` — several drainers are safe.
- Attempts are bounded (`MAX_ATTEMPTS = 5`); exhausted rows become `failed`
  and are **kept**. Deleting them would restore exactly the silent divergence
  this exists to prevent.
- The summary path drains opportunistically so latency matches the old direct
  call; the cron drain (every 2 minutes) is the guarantee.

## Consequences
- A Neo4j outage self-heals: entries accumulate and converge on return.
- Divergence is an observable state — `/health` reports pending count, oldest
  pending age, and `graph_diverged` when anything failed permanently.
- **Cost:** one extra table, one extra write per summary, and a background job.

## Revisit when
A second dual-write target appears (a search index, a warehouse). At that
point `operation` should become a registry of handlers rather than the
current single-branch dispatch.
