#!/usr/bin/env bash
#
# Donna — restore from a backup produced by ./scripts/backup.sh
#
# DESTRUCTIVE. This drops and recreates the application schema. It refuses to
# run without an explicit confirmation, because the failure mode of a restore
# script run by accident is worse than the outage it was meant to fix.
#
# Usage:
#   ./scripts/restore.sh <backup_dir>              # prompts
#   CONFIRM=yes ./scripts/restore.sh <backup_dir>  # non-interactive

set -euo pipefail

BACKUP_DIR="${1:-}"
[ -n "${BACKUP_DIR}" ] || { echo "usage: $0 <backup_dir>" >&2; exit 2; }
[ -d "${BACKUP_DIR}" ] || { echo "no such backup dir: ${BACKUP_DIR}" >&2; exit 2; }

PG_CONTAINER="${PG_CONTAINER:-voice-doc-postgres}"
MINIO_CONTAINER="${MINIO_CONTAINER:-voice-doc-minio}"
QDRANT_HOST="${QDRANT_HOST:-localhost}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
POSTGRES_USER="${POSTGRES_USER:-voicedoc}"
POSTGRES_DB="${POSTGRES_DB:-voice_doc_intel}"

log()  { printf '\033[36m[restore]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[restore]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[31m[restore] FATAL:\033[0m %s\n' "$*" >&2; exit 1; }

[ -f "${BACKUP_DIR}/postgres.dump" ] || fail "postgres.dump missing — this is not a usable backup."

# Integrity check before touching anything live.
if [ -f "${BACKUP_DIR}/MANIFEST.json" ]; then
    log "verifying manifest checksums…"
    python3 - "${BACKUP_DIR}" <<'PY' || exit 1
import hashlib, json, os, sys
d = sys.argv[1]
man = json.load(open(os.path.join(d, "MANIFEST.json")))
bad = []
for rel, meta in man["files"].items():
    p = os.path.join(d, rel)
    if not os.path.exists(p):
        bad.append(f"missing: {rel}"); continue
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    if h.hexdigest() != meta["sha256"]:
        bad.append(f"checksum mismatch: {rel}")
if bad:
    print("[restore] CORRUPT BACKUP:", file=sys.stderr)
    for b in bad:
        print("   -", b, file=sys.stderr)
    sys.exit(1)
print(f"[restore] manifest OK ({len(man['files'])} files)")
PY
else
    warn "no MANIFEST.json — cannot verify integrity before restoring."
fi

if [ "${CONFIRM:-}" != "yes" ]; then
    echo
    warn "This will DROP and recreate schema 'doc_intel' in database '${POSTGRES_DB}'."
    warn "Backup: ${BACKUP_DIR}"
    read -r -p "Type 'restore' to proceed: " answer
    [ "${answer}" = "restore" ] || { echo "aborted."; exit 1; }
fi

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
log "restoring PostgreSQL…"
docker exec -i "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -c "DROP SCHEMA IF EXISTS doc_intel CASCADE;" >/dev/null
docker exec -i "${PG_CONTAINER}" pg_restore \
    -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --no-owner \
    < "${BACKUP_DIR}/postgres.dump" \
    || warn "pg_restore reported errors (often harmless for pre-existing objects) — check output."
log "  postgres restored"

# ---------------------------------------------------------------------------
# MinIO / local uploads
# ---------------------------------------------------------------------------
if [ -d "${BACKUP_DIR}/minio" ]; then
    log "restoring MinIO objects…"
    docker cp "${BACKUP_DIR}/minio/." "${MINIO_CONTAINER}:/data" \
        || warn "MinIO restore failed — original documents are missing."
fi
if [ -d "${BACKUP_DIR}/local-uploads" ]; then
    mkdir -p ./data
    cp -R "${BACKUP_DIR}/local-uploads" ./data/uploads
    log "  local uploads restored"
fi

# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------
if [ -f "${BACKUP_DIR}/qdrant/collections.txt" ]; then
    warn "Qdrant snapshots are stored server-side; recover them with the Qdrant"
    warn "snapshot API, or re-index from Postgres + MinIO (idempotent: point IDs"
    warn "are deterministic UUIDv5, so re-processing overwrites rather than dupes)."
fi

log "restore complete."
log "NEXT: run 'uv run alembic upgrade head' to apply any migrations newer than the dump."
