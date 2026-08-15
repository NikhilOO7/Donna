# ADR-011: Split job queues by latency class

**Status:** Accepted · **Date:** 2026-08

## Context
Arq has no priority or fairness model. Dispatch jobs (live meeting, must be
fast) shared one FIFO queue with document processing (`job_timeout = 600`).
A 100-document upload batch could occupy every worker slot with ten-minute
jobs while the dispatch job for an in-progress meeting waited behind it —
inverting the entire hot/warm/cold model the architecture is built on.

## Decision
Two queues, two worker processes:

| Queue | Jobs | Worker | Timeout |
|-------|------|--------|---------|
| `donna:hot` | `dispatch_job` | `DispatchWorkerSettings` | 90s, `max_jobs=20` |
| `donna:bulk` | research, summary, document processing, outbox drain, cron | `WorkerSettings` | 600s |

Unknown jobs default to **bulk**: a new job is assumed slow until someone
deliberately promotes it.

## Consequences
- Bulk work can no longer starve the live path.
- **Cost:** `USE_JOB_QUEUE=true` now requires *two* worker processes. A
  deployment running only one leaves a queue unconsumed.
- That failure is made visible rather than silent: `/health` reports per-queue
  depth and flags a hot-queue backlog above 50 as
  `"is dispatch-worker running?"`.

## Revisit when
Per-tenant fairness is needed — one tenant's bulk batch still delays another
tenant's bulk work. That requires a queue with real fairness semantics, not
another split.
