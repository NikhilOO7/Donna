#!/usr/bin/env bash
#
# Donna — full stateful backup.
#
# Backs up every stateful store in one consistent-enough snapshot:
#   * PostgreSQL  — system of record (meetings, decisions, action items, docs)
#   * Qdrant      — vector collections (rebuildable from Postgres + MinIO, but
#                   slowly and at OpenAI cost, so back it up)
#   * MinIO       — original uploaded files (NOT rebuildable — the only copy)
#   * Neo4j       — knowledge graph, if running (rebuildable; best-effort)
#
# Redis is deliberately NOT backed up: everything in it is ephemeral by
# design (caches, locks, cooldowns, queue, cost meter). Losing it costs a
# cold cache and in-flight jobs, not data.
#
# Usage:
#   ./scripts/backup.sh [output_dir]
#
# Restore with ./scripts/restore.sh <backup_dir>
# Verify with  ./scripts/verify-backup.sh <backup_dir>

set -euo pipefail

BACKUP_ROOT="${1:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_ROOT}/${STAMP}"

PG_CONTAINER="${PG_CONTAINER:-voice-doc-postgres}"
MINIO_CONTAINER="${MINIO_CONTAINER:-voice-doc-minio}"
QDRANT_HOST="${QDRANT_HOST:-localhost}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
NEO4J_CONTAINER="${NEO4J_CONTAINER:-voice-doc-neo4j}"

POSTGRES_USER="${POSTGRES_USER:-voicedoc}"
POSTGRES_DB="${POSTGRES_DB:-voice_doc_intel}"

log()  { printf '\033[36m[backup]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[backup]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[31m[backup] FATAL:\033[0m %s\n' "$*" >&2; exit 1; }

mkdir -p "${DEST}"
log "writing to ${DEST}"

# ---------------------------------------------------------------------------
# 1. PostgreSQL — the one that must never fail silently
# ---------------------------------------------------------------------------
log "dumping PostgreSQL (${POSTGRES_DB})…"
if ! docker exec "${PG_CONTAINER}" pg_dump \
        -U "${POSTGRES_USER}" \
        -d "${POSTGRES_DB}" \
        --format=custom \
        --no-owner \
        > "${DEST}/postgres.dump" 2>"${DEST}/postgres.err"; then
    cat "${DEST}/postgres.err" >&2
    fail "pg_dump failed — aborting. A backup set without Postgres is worthless."
fi
rm -f "${DEST}/postgres.err"

# An empty/truncated dump is worse than none, because it looks like success.
PG_SIZE=$(wc -c < "${DEST}/postgres.dump" | tr -d ' ')
[ "${PG_SIZE}" -gt 1024 ] || fail "postgres.dump is only ${PG_SIZE} bytes — refusing to record this as a backup."
log "  postgres.dump ${PG_SIZE} bytes"

# ---------------------------------------------------------------------------
# 2. MinIO — original uploads, the only copy that exists
# ---------------------------------------------------------------------------
log "copying MinIO objects…"
if docker exec "${MINIO_CONTAINER}" sh -c 'test -d /data' 2>/dev/null; then
    docker cp "${MINIO_CONTAINER}:/data" "${DEST}/minio" 2>/dev/null \
        || warn "MinIO copy failed — original uploads are NOT backed up."
    log "  minio/ copied"
else
    warn "MinIO container '${MINIO_CONTAINER}' not found — skipping (uploads unprotected)."
fi

# Local-storage mode keeps uploads on a host volume instead.
if [ -d "./data/uploads" ]; then
    cp -R "./data/uploads" "${DEST}/local-uploads"
    log "  local-uploads/ copied"
fi

# ---------------------------------------------------------------------------
# 3. Qdrant — snapshot every collection via the HTTP API
# ---------------------------------------------------------------------------
log "snapshotting Qdrant collections…"
mkdir -p "${DEST}/qdrant"
if COLLECTIONS=$(curl -fsS "http://${QDRANT_HOST}:${QDRANT_PORT}/collections" 2>/dev/null \
                 | python3 -c 'import sys,json; print(" ".join(c["name"] for c in json.load(sys.stdin)["result"]["collections"]))' 2>/dev/null); then
    for c in ${COLLECTIONS}; do
        if curl -fsS -X POST "http://${QDRANT_HOST}:${QDRANT_PORT}/collections/${c}/snapshots" \
             -o "${DEST}/qdrant/${c}.snapshot.json" 2>/dev/null; then
            log "  snapshot: ${c}"
        else
            warn "  snapshot failed: ${c}"
        fi
    done
    echo "${COLLECTIONS}" > "${DEST}/qdrant/collections.txt"
else
    warn "Qdrant unreachable — vectors not backed up (rebuildable from Postgres + MinIO at OpenAI cost)."
fi

# ---------------------------------------------------------------------------
# 4. Neo4j — optional by design, best-effort here too
# ---------------------------------------------------------------------------
if docker ps --format '{{.Names}}' | grep -q "^${NEO4J_CONTAINER}$"; then
    log "dumping Neo4j…"
    docker exec "${NEO4J_CONTAINER}" sh -c \
        'neo4j-admin database dump neo4j --to-stdout 2>/dev/null' \
        > "${DEST}/neo4j.dump" 2>/dev/null \
        || warn "Neo4j dump failed (graph is rebuildable — continuing)."
else
    log "Neo4j not running — skipping (optional store)."
fi

# ---------------------------------------------------------------------------
# 5. Manifest — what a restore should expect to find
# ---------------------------------------------------------------------------
python3 - "$DEST" <<'PY'
import hashlib, json, os, subprocess, sys, datetime

dest = sys.argv[1]

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

files = {}
for root, _dirs, names in os.walk(dest):
    for n in names:
        if n == "MANIFEST.json":
            continue
        p = os.path.join(root, n)
        rel = os.path.relpath(p, dest)
        files[rel] = {"bytes": os.path.getsize(p), "sha256": sha256(p)}

try:
    sha = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], text=True
    ).strip()
except Exception:
    sha = None

manifest = {
    "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "git_sha": sha,
    "files": files,
    "notes": (
        "Redis is intentionally absent: caches, locks, cooldowns, the job "
        "queue and the cost meter are all ephemeral by design."
    ),
}
with open(os.path.join(dest, "MANIFEST.json"), "w") as fh:
    json.dump(manifest, fh, indent=2)
print(f"[backup] manifest: {len(files)} file(s)")
PY

log "done: ${DEST}"
log "VERIFY IT: ./scripts/verify-backup.sh ${DEST}"
log "An unverified backup is a hypothesis, not a backup."
