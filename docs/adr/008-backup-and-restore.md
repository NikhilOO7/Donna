# ADR-008: Backup, restore, and a scheduled restore drill

**Status:** Accepted (partially implemented) · **Date:** 2026-08

## Context
Postgres, Qdrant and MinIO ran as Docker volumes with no automated backup, no
offsite copy and no tested restore path. RPO and RTO were both undefined. Every
other known defect was recoverable; this one was not.

## Decision
Three scripts, and a drill that runs on a schedule:

- `scripts/backup.sh` — Postgres custom-format dump, MinIO objects, Qdrant
  snapshots, optional Neo4j, plus a SHA-256 `MANIFEST.json`. **Aborts** if the
  Postgres dump is implausibly small: a truncated dump that looks like success
  is worse than no dump.
- `scripts/restore.sh` — verifies the manifest *before* touching anything live;
  requires explicit confirmation.
- `scripts/verify-backup.sh` — restores into a throwaway container and asserts
  tables and rows came back.
- `.github/workflows/backup-drill.yml` — exercises backup → destroy → restore
  → assert weekly and on any change to the scripts or migrations.

Redis is deliberately **not** backed up: caches, locks, cooldowns, the queue
and the cost meter are ephemeral by design.

## Consequences
- The restore *procedure* is continuously tested, which is the part that rots.
- Assertions are on outcomes (row counts), not on the absence of errors —
  `pg_restore` warns routinely and "no errors" is not "data present".

## Still open
Nothing schedules a backup of **production** data, and there is no offsite
copy. Remaining work is deployment-shaped: managed Postgres with PITR,
object-store replication, and alerting when a drill fails. Until then RPO/RTO
remain undefined and this ADR is only partially realised.

## Revisit when
The first real customer data lands. At that point the deployment-shaped half
becomes blocking, not merely outstanding.
