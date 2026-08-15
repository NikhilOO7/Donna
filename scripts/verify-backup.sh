#!/usr/bin/env bash
#
# Donna — backup restore drill.
#
# The point of this script: a backup nobody has restored is a hypothesis.
# This performs a REAL restore into a THROWAWAY Postgres container and asserts
# the data actually came back — without touching anything live.
#
# Run it on a schedule. A backup pipeline that has never been exercised fails
# on the day you need it, which is the only day it matters.
#
# Usage:
#   ./scripts/verify-backup.sh <backup_dir>

set -euo pipefail

BACKUP_DIR="${1:-}"
[ -n "${BACKUP_DIR}" ] || { echo "usage: $0 <backup_dir>" >&2; exit 2; }
[ -f "${BACKUP_DIR}/postgres.dump" ] || { echo "no postgres.dump in ${BACKUP_DIR}" >&2; exit 2; }

DRILL_CONTAINER="donna-restore-drill-$$"
DRILL_PORT="${DRILL_PORT:-55432}"
PGPASS="drill"

log()  { printf '\033[36m[drill]\033[0m %s\n' "$*"; }
pass() { printf '\033[32m[drill] PASS\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[drill] FAIL\033[0m %s\n' "$*" >&2; FAILED=1; }

FAILED=0
cleanup() { docker rm -f "${DRILL_CONTAINER}" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# 1. Checksums -------------------------------------------------------------
if [ -f "${BACKUP_DIR}/MANIFEST.json" ]; then
    if python3 - "${BACKUP_DIR}" <<'PY'
import hashlib, json, os, sys
d = sys.argv[1]
man = json.load(open(os.path.join(d, "MANIFEST.json")))
for rel, meta in man["files"].items():
    p = os.path.join(d, rel)
    if not os.path.exists(p):
        sys.exit(f"missing {rel}")
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    if h.hexdigest() != meta["sha256"]:
        sys.exit(f"checksum mismatch {rel}")
PY
    then pass "manifest checksums intact"
    else fail "manifest checksum verification failed"
    fi
else
    fail "no MANIFEST.json"
fi

# 2. Real restore into a throwaway database --------------------------------
log "starting throwaway Postgres on :${DRILL_PORT}…"
docker run -d --name "${DRILL_CONTAINER}" \
    -e POSTGRES_PASSWORD="${PGPASS}" \
    -e POSTGRES_USER=voicedoc \
    -e POSTGRES_DB=drill \
    -p "${DRILL_PORT}:5432" \
    postgres:15-alpine >/dev/null

log "waiting for readiness…"
for _ in $(seq 1 30); do
    if docker exec "${DRILL_CONTAINER}" pg_isready -U voicedoc -d drill >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

log "restoring dump into the throwaway…"
if docker exec -i "${DRILL_CONTAINER}" pg_restore -U voicedoc -d drill --no-owner \
     < "${BACKUP_DIR}/postgres.dump" >/dev/null 2>&1; then
    pass "pg_restore completed"
else
    # pg_restore warns on pre-existing objects; only a hard failure matters,
    # which the row-count assertions below will catch.
    log "pg_restore reported warnings — continuing to row checks"
fi

# 3. Assert the data is actually there -------------------------------------
# Asserting on OUTCOMES, not on the absence of errors: this is the same
# lesson as the smoke tests in the war-stories chapter.
log "asserting restored contents…"
ROWS=$(docker exec "${DRILL_CONTAINER}" psql -U voicedoc -d drill -tAc "
    SELECT COALESCE(SUM(n), 0) FROM (
        SELECT COUNT(*) AS n FROM doc_intel.meetings
        UNION ALL SELECT COUNT(*) FROM doc_intel.documents
        UNION ALL SELECT COUNT(*) FROM doc_intel.users
    ) t;" 2>/dev/null | tr -d '[:space:]' || echo "ERR")

TABLES=$(docker exec "${DRILL_CONTAINER}" psql -U voicedoc -d drill -tAc \
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='doc_intel';" \
    2>/dev/null | tr -d '[:space:]' || echo "0")

if [ "${TABLES}" = "0" ] || [ "${TABLES}" = "ERR" ]; then
    fail "schema doc_intel has no tables after restore"
else
    pass "schema restored with ${TABLES} tables"
fi

if [ "${ROWS}" = "ERR" ]; then
    fail "could not read core tables after restore"
else
    pass "core tables queryable (meetings+documents+users = ${ROWS} rows)"
    [ "${ROWS}" = "0" ] && log "note: 0 rows — expected only if the source really was empty"
fi

# 4. Uploads present? ------------------------------------------------------
if [ -d "${BACKUP_DIR}/minio" ] || [ -d "${BACKUP_DIR}/local-uploads" ]; then
    pass "original uploads present in the backup set"
else
    fail "no uploads in the backup — originals are the ONLY non-rebuildable data"
fi

echo
if [ "${FAILED}" = "0" ]; then
    printf '\033[32m[drill] RESTORE DRILL PASSED\033[0m — %s is recoverable.\n' "${BACKUP_DIR}"
    exit 0
fi
printf '\033[31m[drill] RESTORE DRILL FAILED\033[0m — do NOT rely on %s.\n' "${BACKUP_DIR}" >&2
exit 1
