# ADR-005: Modular monolith + workers, not microservices

**Status:** Accepted · **Date:** 2026-08

## Context
Donna's domain objects — meeting, transcript, nudge, decision, action item —
are deeply interrelated. Nearly every operation touches several at once. The
default modern instinct is to split by domain into services.

## Decision
One FastAPI backend holds all domain logic. Three worker processes are split
out, and only for reasons of **resource isolation**, not domain boundaries:

- `job-worker` / `dispatch-worker` — CPU-heavy OCR and latency-sensitive dispatch
- `voice-worker` — long-lived audio streams
- `assistant-worker` — the conversational agent

Workers import from `apps/api`, reusing the same service layer and models.

## Consequences
- In-process function calls instead of network calls, with no distributed
  transactions across objects that are always mutated together.
- One source of truth for business logic; a bugfix applies everywhere with no
  version skew.
- **Cost:** worker images contain the whole application, including
  dependencies they never use (the voice worker ships Docling). Image size and
  cold start suffer; a dependency patch rebuilds everything.

## Revisit when
A worker needs to deploy on a different cadence than the API. The moment you
want to ship a voice-worker hotfix without redeploying the backend, the shared
image stops being a simplification and becomes a coupling. The seams for the
split already exist: they are the router/service boundaries.
