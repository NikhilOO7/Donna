# ADR-006: One Redis for cache, locks, pub/sub, queue, and counters

**Status:** Accepted · **Date:** 2026-08

## Context
Five distinct needs, each of which independently justifies a tool: response
and embedding caching, per-meeting distributed locking, cross-replica event
fan-out, a durable job queue, and counters (cost meter, cooldowns,
learned-mute).

## Decision
Serve all five from one Redis. Every use site is written to **degrade rather
than fail** when Redis is unavailable.

## Consequences
- One connection pool, one health check, one failure mode to reason about.
- **One blast radius.** A Redis outage touches five subsystems at once. This
  is only acceptable because each degrades explicitly:
  locks → process-local, hub → in-process delivery, queue → `BackgroundTasks`,
  caches → miss, meter → drops writes.
- Those degradations are now *audible*: they log at WARNING through
  `warn_throttled()` rather than at DEBUG (which is invisible in production).

## Revisit when
- Job-queue throughput competes with pub/sub for the same event loop — split
  the queue onto its own instance first, not onto a new technology.
- Priorities or per-tenant fairness are needed. Arq models neither; that is
  the point at which the queue specifically outgrows this choice.
