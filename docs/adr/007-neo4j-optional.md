# ADR-007: Neo4j as an optional enhancer, never a dependency

**Status:** Accepted · **Date:** 2026-08

## Context
Two agents want real graph traversal: `kg_query` ("vendor X appears in the Q3
contract *and* the security audit") and `memory` (the Meeting→Decision→Topic
subgraph). Both are multi-hop queries whose SQL form is a recursive CTE nobody
wants to maintain. But a fifth datastore violates the operational-simplicity
driver.

## Decision
Use Neo4j, and make it **structurally optional**: gated by `NEO4J_ENABLED`,
detected at startup and per call, deliberately **not in `docker-compose.yml`**.
An unreachable Neo4j costs two nudge types and nothing else.

## Consequences
- Graph capability without making the core product depend on a store most
  deployments will not run.
- Every KG call site must handle absence — enforced by the degradation ladder.
- Writes go through the outbox (ADR-009), so an outage converges rather than
  diverging.

## Revisit when
Either direction, decided by data now that
`GET /api/v1/meetings/nudge-acceptance` exists:
- If graph nudges rank **high** in acceptance, Neo4j graduates into compose as
  a real dependency with a backup story.
- If they rank **low**, both agents and the store come out, and the ingestion
  relationship agent's output becomes dead weight worth deleting.

This decision is explicitly **open pending that measurement**.
